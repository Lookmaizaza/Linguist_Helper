import re
import time
import html
import concurrent.futures
from io import BytesIO
import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup
import os
import importlib

# Suppress TensorFlow warnings
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

# --- ตรวจสอบ Library ---
try:
    import trafilatura
    TRAFILATURA_AVAILABLE = True
except ImportError:
    TRAFILATURA_AVAILABLE = False

try:
    import deepcut
    DEEPCUT_AVAILABLE = True
except ImportError:
    DEEPCUT_AVAILABLE = False

def tokenize_text(text: str):
    """Tokenize text using deepcut with robust session recovery"""
    if not DEEPCUT_AVAILABLE or not text:
        return text.split() if text else []
    
    try:
        from deepcut import tokenize
        return tokenize(text)
    except Exception as e1:
        # Session corrupted - reload deepcut module completely
        try:
            import tensorflow as tf
            tf.keras.backend.clear_session()
            
            # Reload deepcut to reinitialize the tokenizer
            import deepcut as dc
            importlib.reload(dc)
            from deepcut import tokenize
            return tokenize(text)
        except Exception as e2:
            # Ultimate fallback to word split
            return text.split()

# --- Pre-compile Regex & Junk ---
RE_CLEAN = re.compile(r"[\u200B-\u200D\uFEFF]")
RE_KEEP = re.compile(r"[^a-zA-Zก-ฮะ-์0-9\.\s]")
JUNK_KEYWORDS = {"หวย", "ดวง", "โฆษณา", "อ่านต่อ", "คลิก", "หน้าแรก", "เมนู", "Login"}

def clean_text_final(text: str) -> str:
    if not text: return ""
    lines = []
    for ln in text.splitlines():
        ln = ln.strip()
        # กรองบรรทัดขยะมาตรฐาน
        if len(ln) < 40 and any(j in ln for j in JUNK_KEYWORDS): continue
        if ln: lines.append(ln)
    
    text = "\n".join(lines)
    text = html.unescape(text)
    text = RE_CLEAN.sub("", text)
    text = RE_KEEP.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()

def get_content_universal(url: str):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        # โหลดหน้าเว็บ
        res = requests.get(url, headers=headers, timeout=12)
        res.raise_for_status()
        res.encoding = res.apparent_encoding
        soup = BeautifulSoup(res.content, 'html.parser')

        # --- แผน 1: Sniper Mode (เจาะจง ID/Class) ---
        # รายชื่อเป้าหมายยอดฮิตของเว็บข่าวไทย/เทศ
        targets = [
            {'class': 'EntryReaderInner'}, {'id': 'EntryReader_0'}, # Sanook
            {'class': 'article-body'}, {'itemprop': 'articleBody'}, # Standard Semantic
            {'class': 'content-detail'}, {'class': 'news-detail'},  # General Thai News
            {'class': 'story-body'}, {'role': 'main'}               # BBC / Others
        ]
        
        for attrs in targets:
            # หา div หรือ article ที่มี attributes ตามเป้าหมาย
            node = soup.find(['div', 'article', 'section'], attrs)
            if node:
                # ลบขยะในก้อนเนื้อหา (เช่น โฆษณาคั่นบรรทัด)
                for junk in node(['script', 'style', 'div.ads', 'div.related']):
                    junk.decompose()
                return clean_text_final(node.get_text(separator="\n")), "Sniper (Targeted)"

        # --- แผน 2: AI Mode (Trafilatura) ---
        # ถ้าหาเป้าหมายไม่เจอ ให้ Trafilatura ช่วยวิเคราะห์
        if TRAFILATURA_AVAILABLE:
            # favor_precision=True ช่วยให้ไม่ดึงเมนูติดมา
            extracted = trafilatura.extract(res.content, include_comments=False, favor_precision=True)
            if extracted:
                return clean_text_final(extracted), "AI (Trafilatura)"

        # --- แผน 3: Sweep Mode (กวาดทั้งหมดแบบมีการกรอง) ---
        # ลบแท็กขยะออกให้หมดก่อน
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'button', 'form', 'iframe']):
            tag.decompose()
        
        # ดึง text ทั้งหมดที่เหลืออยู่
        raw_text = soup.get_text(separator="\n")
        return clean_text_final(raw_text), "Fallback (Sweep)"

    except Exception as e:
        return "", f"Error: {str(e)}"

# --- UI Logic ---
st.set_page_config(page_title="Linguist Pro: Universal", layout="wide")
st.title("🌐 The Linguist's Assistant (Universal Mode)")

# Initialize session state for accumulating results
if "all_results" not in st.session_state:
    st.session_state.all_results = []  # List of analyses
if "show_results" not in st.session_state:
    st.session_state.show_results = False

# Top buttons for navigation
col1, col2, col3 = st.columns([1, 1, 8])
with col1:
    if st.button("📝 ป้อนข้อมูล", use_container_width=True):
        st.session_state.show_results = False
        st.rerun()
with col2:
    if len(st.session_state.all_results) > 0:
        if st.button("📊 ผลลัพธ์ทั้งหมด", use_container_width=True):
            st.session_state.show_results = True
            st.rerun()

st.divider()

# PAGE 1: INPUT
if not st.session_state.show_results:
    st.markdown("### ป้อนข้อมูลที่ต้องการวิเคราะห์")
    
    # Toggle between URL and Text input
    input_type = st.radio("เลือกประเภทข้อมูล:", ["🔗 URL", "📝 ข้อความ"], horizontal=True)
    
    if input_type == "🔗 URL":
        user_input = st.text_area("วาง URL (หลายรายการขึ้นบรรทัดใหม่):", height=150, placeholder="https://example.com", key="url_input")
    else:
        user_input = st.text_area("วาง ข้อความ (หลายข้อความขึ้นบรรทัดใหม่):", height=150, placeholder="ข้อความที่ต้องการวิเคราะห์", key="text_input")
    
    col_analyze, col_clear = st.columns([5, 1])
    
    with col_analyze:
        if st.button("🚀 เริ่มการวิเคราะห์", type="primary", use_container_width=True):
            items = [ln.strip() for ln in user_input.splitlines() if ln.strip()]
            if not items:
                st.warning("⚠️ กรุณาป้อนข้อมูลอย่างน้อยหนึ่งรายการ")
                st.stop()
        
            results = []
            
            if input_type == "🔗 URL":
                # Process URLs
                with st.status("กำลังทำงานด้วยระบบ 3-Layer Safety Net...", expanded=True) as status:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                        future_to_url = {executor.submit(get_content_universal, url): url for url in items}
                        for future in concurrent.futures.as_completed(future_to_url):
                            url = future_to_url[future]
                            content, method = future.result()
                            
                            if content:
                                status.write(f"✅ {url} -> สำเร็จด้วยวิธี: {method}")
                                tokens = tokenize_text(content)
                                results.append({"Source": url, "Raw": content, "Tokens": tokens, "Method": method})
                            else:
                                status.write(f"❌ {url} -> ไม่พบเนื้อหา")
            else:
                # Process text input
                with st.status("กำลังวิเคราะห์ข้อความ...", expanded=True) as status:
                    for idx, text in enumerate(items, 1):
                        cleaned_text = clean_text_final(text)
                        if cleaned_text:
                            status.write(f"✅ ข้อความ {idx} -> สำเร็จ")
                            tokens = tokenize_text(cleaned_text)
                            results.append({"Source": f"ข้อความ {idx}", "Raw": cleaned_text, "Tokens": tokens, "Method": "Direct Text"})
                        else:
                            status.write(f"❌ ข้อความ {idx} -> ไม่มีเนื้อหา")
            
            if results:
                # Add to accumulated results with timestamp
                import datetime
                analysis_entry = {
                    "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "data": results
                }
                st.session_state.all_results.append(analysis_entry)
                st.session_state.show_results = True
                st.session_state.current_result_idx = len(st.session_state.all_results) - 1
                st.success(f"✅ การวิเคราะห์เสร็จสิ้น! เพิ่ม {len(results)} URL")
                st.info(f"📊 จำนวนการวิเคราะห์ทั้งหมด: {len(st.session_state.all_results)}")
                st.rerun()
            else:
                st.error("❌ ไม่พบผลลัพธ์ใด ๆ")
    
    with col_clear:
        if st.button("🗑️", help="ลบผลลัพธ์ทั้งหมด", use_container_width=True):
            st.session_state.all_results = []
            st.success("✅ ลบข้อมูลแล้ว")
            st.rerun()
    
    # Show summary of all analyses
    if len(st.session_state.all_results) > 0:
        st.divider()
        st.subheader("📋 ประวัติการวิเคราะห์")
        for idx, analysis in enumerate(st.session_state.all_results, 1):
            col1, col2 = st.columns([4, 1])
            with col1:
                st.write(f"**{idx}. {analysis['timestamp']}** - {len(analysis['data'])} URL")
            with col2:
                if st.button("ดูผลลัพธ์", key=f"view_{idx}"):
                    st.session_state.show_results = True
                    st.session_state.current_result_idx = idx - 1
                    st.rerun()

# PAGE 2: RESULTS
else:
    if len(st.session_state.all_results) == 0:
        st.info("📭 ไม่มีข้อมูล")
    else:
        # Select which analysis to view
        if "current_result_idx" not in st.session_state:
            st.session_state.current_result_idx = len(st.session_state.all_results) - 1
        
        col1, col2 = st.columns([1, 5])
        with col1:
            result_options = [f"#{idx + 1} - {analysis['timestamp']}" 
                            for idx, analysis in enumerate(st.session_state.all_results)]
            selected_idx = st.selectbox("เลือกการวิเคราะห์:", 
                                       range(len(st.session_state.all_results)),
                                       format_func=lambda x: result_options[x])
            st.session_state.current_result_idx = selected_idx
        
        results = st.session_state.all_results[st.session_state.current_result_idx]["data"]
        
        # สร้าง DataFrame
        df = pd.DataFrame(results)
        
        # Summary Sheet
        df_sum = df[["Source", "Method", "Raw"]].copy()
        df_sum["Word Count"] = df["Tokens"].apply(len)
        df_sum["Tokenized"] = df["Tokens"].apply(lambda x: "|".join(x))
        
        # Word List Sheet
        df_words = df[["Source", "Tokens"]].explode("Tokens").rename(columns={"Tokens": "Word"})
        df_words["Index"] = df_words.groupby("Source").cumcount() + 1
        
        # ===== Enhanced Results Display =====
        st.success("✅ ผลการวิเคราะห์")
        
        # Metrics Row
        cols = st.columns(4)
        with cols[0]:
            st.metric("📄 จำนวน URL", len(results))
        with cols[1]:
            total_words = df_sum["Word Count"].sum()
            st.metric("📝 รวมคำศัพท์", int(total_words))
        with cols[2]:
            avg_words = df_sum["Word Count"].mean()
            st.metric("📊 คำศัพท์เฉลี่ย", f"{avg_words:.0f}")
        with cols[3]:
            st.metric("⚙️ วิธีใช้", df_sum["Method"].mode()[0] if len(df_sum) > 0 else "N/A")
        
        st.divider()
        
        # Tabs for different views
        tab1, tab2, tab3 = st.tabs(["📋 สรุปผล", "🔤 คำศัพท์แต่ละคำ", "📥 ดาวน์โหลด"])
        
        with tab1:
            st.subheader("รายละเอียดการวิเคราะห์แต่ละ URL")
            for idx, row in df_sum.iterrows():
                with st.expander(f"🔗 {row['Source']}", expanded=(idx == 0)):
                    col1, col2 = st.columns([2, 1])
                    with col1:
                        st.write("**ข้อความต้นฉบับ:**")
                        st.write(row['Raw'][:500] + ("..." if len(row['Raw']) > 500 else ""))
                    with col2:
                        st.write("**สถิติ:**")
                        st.info(f"🎯 วิธี: {row['Method']}\n\n📊 คำศัพท์: {row['Word Count']}")
                    
                    st.write("**โทเคนที่ตัดแล้ว:**")
                    tokens = df.iloc[idx]['Tokens']
                    # Display tokens in nice pills
                    token_html = " ".join([f"<span style='background-color: #E8F4F8; padding: 5px 10px; margin: 3px; border-radius: 15px; display: inline-block; font-size: 12px;'>{token}</span>" for token in tokens[:50]])
                    st.markdown(f"<div>{token_html}</div>", unsafe_allow_html=True)
                    if len(tokens) > 50:
                        st.caption(f"... และอีก {len(tokens) - 50} คำ")
        
        with tab2:
            st.subheader("รายการคำศัพท์ทั้งหมด")
            # Count word frequency
            word_freq = df_words['Word'].value_counts().head(30)
            col1, col2 = st.columns([1, 1])
            
            with col1:
                st.write("**30 คำที่ปรากฏบ่อยที่สุด:**")
                for word, count in word_freq.items():
                    st.text(f"• {word} ({count})")
            
            with col2:
                st.bar_chart(word_freq)
            
            st.dataframe(df_words[["Source", "Word", "Index"]], use_container_width=True)
        
        with tab3:
            st.subheader("ดาวน์โหลดผลลัพธ์")
            col1, col2 = st.columns(2)
            
            with col1:
                # Export to Excel
                output = BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    df_sum.to_excel(writer, index=False, sheet_name='Summary')
                    df_words.to_excel(writer, index=False, sheet_name='Detailed_Words')
                
                st.download_button(
                    label="📥 ดาวน์โหลด Excel (.xlsx)",
                    data=output.getvalue(),
                    file_name=f"linguist_analysis_{st.session_state.all_results[st.session_state.current_result_idx]['timestamp'].replace(':', '-')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True
                )
            
            with col2:
                # Export to CSV
                csv = df_words.to_csv(index=False, encoding='utf-8-sig')
                st.download_button(
                    label="📄 ดาวน์โหลด CSV (.csv)",
                    data=csv,
                    file_name=f"linguist_analysis_{st.session_state.all_results[st.session_state.current_result_idx]['timestamp'].replace(':', '-')}.csv",
                    mime="text/csv",
                    use_container_width=True
                )