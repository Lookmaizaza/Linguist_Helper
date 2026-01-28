import re
import html
from io import BytesIO
import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup
import os
from datetime import datetime

# Suppress TensorFlow warnings
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

# --- ตรวจสอบ Library ---
try:
    import attacut
    ATTACUT_AVAILABLE = True
except ImportError:
    ATTACUT_AVAILABLE = False

try:
    import deepcut
    DEEPCUT_AVAILABLE = True
except ImportError:
    DEEPCUT_AVAILABLE = False

def tokenize_text(text: str):
    """Tokenize Thai text using attacut (or deepcut as fallback)"""
    if not text:
        return []
    
    try:
        # Try attacut first (more accurate)
        if ATTACUT_AVAILABLE:
            return attacut.tokenize(text)
        elif DEEPCUT_AVAILABLE:
            from deepcut import tokenize
            return tokenize(text)
        else:
            return text.split()
    except Exception as e:
        # Fallback to word split
        return text.split()

def clean_text_final(text: str) -> str:
    """Clean and normalize text"""
    if not text: 
        return ""
    
    # Remove zero-width characters and other invisible characters
    text = re.sub(r"[\u200B-\u200D\uFEFF]", "", text)
    # Unescape HTML entities
    text = html.unescape(text)
    # Remove extra whitespace
    text = re.sub(r"\s+", " ", text).strip()
    
    return text

def get_content_universal(url: str):
    """Extract main content from webpage"""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        res = requests.get(url, headers=headers, timeout=12)
        res.raise_for_status()
        res.encoding = res.apparent_encoding
        soup = BeautifulSoup(res.content, 'html.parser')

        # ลบแท็กขยะก่อน
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'button', 'form', 'iframe', 'noscript']):
            tag.decompose()

        # แผน 1: เจาะจง (Sniper)
        targets = [
            {'class': 'EntryReaderInner'}, {'id': 'EntryReader_0'},          # Sanook
            {'class': 'article-body'}, {'itemprop': 'articleBody'},          # Standard
            {'class': 'content-detail'}, {'class': 'news-detail'},           # Thai News
            {'class': 'story-body'}, {'class': 'article-content'},           # General
            {'role': 'main'},                                                # Semantic
        ]
        
        for attrs in targets:
            node = soup.find(['div', 'article', 'section', 'main'], attrs)
            if node:
                return clean_text_final(node.get_text(separator="\n"))

        # แผน 2: กวาด (Sweep) - ดึงเนื้อหาที่เหลือ
        raw_text = soup.get_text(separator="\n")
        cleaned = clean_text_final(raw_text)
        
        if len(cleaned) > 100:
            return cleaned
        else:
            return ""

    except Exception as e:
        return ""

# --- UI Configuration ---
st.set_page_config(page_title="Linguist Helper Tool", layout="centered", initial_sidebar_state="collapsed")

# Initialize session state
if "current_result" not in st.session_state:
    st.session_state.current_result = None

# --- HEADER ---
st.title("📂 Linguist Helper Tool (v1.0)")
st.markdown("*เครื่องมือช่วยดึงบทความและตัดคำสำหรับงานวิจัย*")
st.divider()

# --- INPUT SECTION ---
st.markdown("### 1. ใส่ลิงก์บทความ (URL):")
user_url = st.text_input(
    "URL",
    placeholder="https://www.thairath.co.th/news/...",
    label_visibility="collapsed",
    key="url_input"
)

col1, col2 = st.columns([3, 1])
with col1:
    if st.button("🔍 ดึงข้อมูลและตัดคำ", type="primary", use_container_width=True):
        if not user_url or not user_url.strip():
            st.error("⚠️ กรุณากรอก URL")
            st.stop()
        
        # Process URL
        with st.status("⏳ กำลังดึงข้อมูล...", expanded=True) as status:
            content = get_content_universal(user_url)
            
            if content and len(content.strip()) > 50:
                status.update(label="✅ ดึงข้อมูลสำเร็จ", state="complete")
                
                # Tokenize
                tokens = tokenize_text(content)
                token_count = len(tokens)
                unique_tokens = len(set(tokens))
                
                # Store result
                st.session_state.current_result = {
                    "url": user_url,
                    "original_text": content,
                    "tokens": tokens,
                    "token_count": token_count,
                    "unique_tokens": unique_tokens,
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                st.rerun()
            else:
                status.update(label="❌ ไม่สามารถดึงข้อมูลได้", state="error")
                st.error("ไม่สามารถดึงเนื้อหาจาก URL นี้ได้ โปรดลองใช้ URL อื่น")

with col2:
    if st.button("🗑️", help="ล้างผลลัพธ์", use_container_width=True):
        st.session_state.current_result = None
        st.rerun()

# --- RESULTS SECTION ---
if st.session_state.current_result:
    st.divider()
    result = st.session_state.current_result
    
    st.markdown("### 📊 สถิติเบื้องต้น:")
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("จำนวนคำทั้งหมด", f"{result['token_count']:,}")
    with col2:
        st.metric("คำศัพท์ที่ไม่ซ้ำ", f"{result['unique_tokens']:,}")
    
    st.markdown("### 📝 ผลลัพธ์การตัดคำ (Tokenized Text):")
    st.text_area(
        "Tokens",
        value=" | ".join(result['tokens']),
        height=100,
        disabled=True,
        label_visibility="collapsed",
        key="tokenized_text"
    )
    
    st.markdown("### 💾 ส่วนดาวน์โหลดข้อมูล:")
    
    col1, col2 = st.columns(2)
    
    # Export to XLSX
    with col1:
        xlsx_buffer = BytesIO()
        with pd.ExcelWriter(xlsx_buffer, engine='openpyxl') as writer:
            # Sheet 1: Summary
            summary_df = pd.DataFrame({
                "URL": [result['url']],
                "Word Count": [result['token_count']],
                "Unique Words": [result['unique_tokens']],
                "Generated": [result['timestamp']]
            })
            summary_df.to_excel(writer, sheet_name='Summary', index=False)
            
            # Sheet 2: Tokens
            tokens_df = pd.DataFrame({
                "Word": result['tokens'],
                "Index": range(1, len(result['tokens']) + 1)
            })
            tokens_df.to_excel(writer, sheet_name='Tokens', index=False)
            
            # Sheet 3: Original Text
            text_df = pd.DataFrame({
                "Original Text": [result['original_text']]
            })
            text_df.to_excel(writer, sheet_name='Original Text', index=False)
        
        st.download_button(
            label="📊 Download Excel (.xlsx)",
            data=xlsx_buffer.getvalue(),
            file_name=f"linguist_result_{result['timestamp'].replace(':', '-')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    
    # Export to TXT
    with col2:
        txt_data = "=" * 80 + "\n"
        txt_data += "LINGUIST ANALYSIS REPORT\n"
        txt_data += f"Generated: {result['timestamp']}\n"
        txt_data += f"URL: {result['url']}\n"
        txt_data += "=" * 80 + "\n\n"
        txt_data += f"Original Text:\n{result['original_text']}\n\n"
        txt_data += f"Tokenized:\n{' | '.join(result['tokens'])}\n\n"
        txt_data += f"Statistics:\n"
        txt_data += f"- Total Tokens: {result['token_count']}\n"
        txt_data += f"- Unique Tokens: {result['unique_tokens']}\n"
        
        st.download_button(
            label="📝 Download Text (.txt)",
            data=txt_data,
            file_name=f"linguist_result_{result['timestamp'].replace(':', '-')}.txt",
            mime="text/plain; charset=utf-8",
            use_container_width=True
        )

# --- FOOTER ---
st.divider()