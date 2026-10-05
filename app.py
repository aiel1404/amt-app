import os
import time
import random
from datetime import datetime

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

# تنظیمات اولیه صفحه
st.set_page_config(page_title="آزمون حافظه اتوبیوگرافیک (AMT)", layout="centered")

# -------------------------------------------------------------------
# استایل راست‌چین (RTL) و فونت بزرگ برای کلمه
# -------------------------------------------------------------------
st.markdown("""
    <style>
    html, body, [data-testid="stAppViewContainer"], div[data-testid="stMarkdownContainer"] {
        direction: rtl;
        text-align: right;
    }
    input, textarea {
        direction: rtl !important;
        text-align: right !important;
    }
    label {
        direction: rtl !important;
        text-align: right !important;
    }
    .word-box {
        background-color: #f0f4f8;
        border-radius: 16px;
        padding: 40px 20px;
        text-align: center;
        font-size: 65px;
        font-weight: 900;
        color: #0d47a1;
        margin-top: 15px;
        margin-bottom: 25px;
        border: 3px solid #90caf9;
        box-shadow: 0 4px 12px rgba(0,0,0,0.08);
    }
    .hidden-word-box {
        background-color: #fff8e1;
        border-radius: 16px;
        padding: 30px 20px;
        text-align: center;
        font-size: 24px;
        font-weight: bold;
        color: #f57f17;
        margin-top: 15px;
        margin-bottom: 25px;
        border: 2px dashed #ffe082;
    }
    .instruction-card {
        background-color: #f9f9f9;
        border: 1px solid #e0e0e0;
        border-right: 5px solid #1f77b4;
        padding: 20px;
        border-radius: 8px;
        margin-bottom: 20px;
        line-height: 1.8;
    }
    .example-card {
        background-color: #e8f4f8;
        border-radius: 6px;
        padding: 12px 15px;
        margin-top: 10px;
        font-size: 15px;
    }
    </style>
""", unsafe_allow_html=True)

AMT_FILE = "amt_responses.csv"
MAX_VIEW_TIME = 30    # حداکثر زمان یادآوری کلمه (ثانیه)
TYPE_TIME = 60        # زمان تایپ پس از ناپدید شدن کلمه (ثانیه)
COMMIT_GRACE = 2.0    # چند ثانیه صبر می‌کنیم تا آخرین متن تایپ‌شده به سرور برسد

COLUMNS = [
    "Timestamp", "Subject_ID", "Word_Index", "Word", "Category",
    "Response_Text", "Retrieval_Latency_Sec", "Typing_Duration_Sec",
    "Total_Time_Sec", "Time_Out",
]


# ===================================================================
# ذخیره‌سازی: Google Sheets (با gspread) + نسخه پشتیبان CSV محلی
# ===================================================================
@st.cache_resource(show_spinner=False)
def get_worksheet():
    """اتصال به Google Sheet با Service Account (فقط یک‌بار ساخته می‌شود)."""
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=scopes
    )
    client = gspread.authorize(creds)

    cfg = st.secrets["gsheet"]
    if "url" in cfg:
        sh = client.open_by_url(cfg["url"])
    else:
        sh = client.open(cfg["name"])

    ws = sh.worksheet(cfg["worksheet"]) if "worksheet" in cfg else sh.sheet1

    # اگر شیت خالی است، سطر عنوان‌ها را اضافه کن
    if not ws.row_values(1):
        ws.append_row(COLUMNS, value_input_option="RAW")
    return ws


def save_to_sheets(row):
    """ارسال یک سطر به Google Sheets با ۳ بار تلاش. خروجی: (موفق؟، پیام خطا)"""
    last_err = ""
    for attempt in range(3):
        try:
            ws = get_worksheet()
            ws.append_row(row, value_input_option="RAW")
            return True, ""
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
            get_worksheet.clear()   # اتصال را از نو بساز
            time.sleep(1 + attempt)
    return False, last_err


def save_data(data_dict):
    """ذخیره همزمان در CSV محلی (پشتیبان) و Google Sheets."""
    record = {"Timestamp": datetime.now().isoformat(timespec="seconds"), **data_dict}
    record = {col: record.get(col, "") for col in COLUMNS}

    # ۱. نسخه پشتیبان محلی
    try:
        df_new = pd.DataFrame([record])
        file_exists = os.path.isfile(AMT_FILE)
        df_new.to_csv(
            AMT_FILE, mode="a" if file_exists else "w",
            header=not file_exists, index=False, encoding="utf-8-sig",
        )
    except Exception as e:  # noqa: BLE001
        st.session_state.save_errors.append(f"CSV: {e}")

    # ۲. Google Sheets
    ok, err = save_to_sheets([record[c] for c in COLUMNS])
    if not ok:
        st.session_state.save_errors.append(f"Sheets (کلمه {record['Word_Index']}): {err}")


# ===================================================================
# وضعیت اولیه برنامه
# ===================================================================
def init_state():
    defaults = {
        "page": "intro",
        "subject_id": "",
        "word_index": 0,
        "phase": "viewing",          # 'viewing' یا 'typing'
        "phase_start_time": None,
        "view_duration": 0.0,
        "last_saved_idx": -1,        # جلوگیری از ذخیره دوباره یک کلمه
        "save_errors": [],
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    if "amt_words" not in st.session_state:
        pos = [("مثبت", w) for w in ["شاد", "موفق", "امیدوار", "آرام", "دوست داشتنی", "افتخار"]]
        neg = [("منفی", w) for w in ["غمگین", "شکست", "تنها", "نا امید", "بی ارزش", "خسته"]]
        neu = [("خنثی", w) for w in ["میز", "صندلی", "لیوان", "دیوار", "خودکار", "نیمکت"]]
        words = pos + neg + neu
        random.shuffle(words)
        st.session_state.amt_words = words


init_state()


def finish_word(response_text, latency, typing_time, timed_out):
    """ثبت پاسخ کلمه فعلی و رفتن به کلمه بعدی (فقط یک‌بار برای هر کلمه)."""
    idx = st.session_state.word_index
    if st.session_state.last_saved_idx == idx:
        return
    st.session_state.last_saved_idx = idx

    category, word = st.session_state.amt_words[idx]
    save_data({
        "Subject_ID": st.session_state.subject_id,
        "Word_Index": idx + 1,
        "Word": word,
        "Category": category,
        "Response_Text": response_text,
        "Retrieval_Latency_Sec": latency,
        "Typing_Duration_Sec": typing_time,
        "Total_Time_Sec": round(latency + typing_time, 2),
        "Time_Out": timed_out,
    })

    st.session_state.word_index += 1
    st.session_state.phase = "viewing"
    st.session_state.phase_start_time = time.time()
    st.session_state.view_duration = 0.0
    st.rerun()


# ===================================================================
# فاز ۱: مشاهده کلمه (تایمر با fragment، بدون time.sleep)
# ===================================================================
@st.fragment(run_every=1)
def viewing_screen():
    idx = st.session_state.word_index
    _, word = st.session_state.amt_words[idx]
    elapsed = time.time() - st.session_state.phase_start_time

    if elapsed >= MAX_VIEW_TIME:
        finish_word("بدون پاسخ (عدم یادآوری در ۳۰ ثانیه)", MAX_VIEW_TIME, 0, True)
        return

    rem = max(0, int(MAX_VIEW_TIME - elapsed))
    st.markdown(f'<div class="word-box">{word}</div>', unsafe_allow_html=True)
    st.info(f"👀 **فرصت یادآوری:** {rem} ثانیه باقی‌مانده است...")

    if st.button("💡 خاطره به ذهنم آمد / شروع تایپ", use_container_width=True):
        st.session_state.view_duration = round(elapsed, 2)
        st.session_state.phase = "typing"
        st.session_state.phase_start_time = time.time()
        st.rerun()


# ===================================================================
# فاز ۲: تایپ خاطره (۶۰ ثانیه) با ذخیره خودکار متن نیمه‌کاره
# ===================================================================
@st.fragment(run_every=1)
def typing_fragment():
    idx = st.session_state.word_index
    key = f"amt_text_{idx}"
    elapsed = time.time() - st.session_state.phase_start_time

    # پایان ۶۰ ثانیه: هر چه تا الان تایپ شده ذخیره می‌شود
    if elapsed >= TYPE_TIME + COMMIT_GRACE:
        text = (st.session_state.get(key) or "").strip()
        finish_word(
            text if text else "نیمه‌کاره/خالی (اتمام ۶۰ ثانیه تایپ)",
            st.session_state.view_duration, TYPE_TIME, True,
        )
        return

    rem = max(0, int(TYPE_TIME - elapsed))
    st.markdown(
        '<div class="hidden-word-box">🙈 کلمه ناپدید شد! خاطره خود را تایپ کنید.</div>',
        unsafe_allow_html=True,
    )
    st.warning(f"✍️ **زمان باقی‌مانده جهت تایپ خاطره:** {rem} ثانیه")

    memory_text = st.text_area("خاطره خود را تایپ کنید:", key=key, height=140)

    if st.button("ثبت و کلمه بعدی", use_container_width=True):
        typing_time = round(time.time() - st.session_state.phase_start_time, 2)
        finish_word(
            memory_text.strip() if memory_text.strip() else "خالی",
            st.session_state.view_duration, typing_time, False,
        )


def typing_screen():
    """
    مرورگر متن textarea را فقط وقتی به سرور می‌فرستد که فوکوس از آن برود.
    این اسکریپت چند لحظه قبل از پایان ۶۰ ثانیه، فوکوس را برای لحظه‌ای برمی‌دارد
    و دوباره برمی‌گرداند تا آخرین متن تایپ‌شده به سرور برسد و ذخیره شود.
    """
    remaining_ms = int(max(0, TYPE_TIME - (time.time() - st.session_state.phase_start_time)) * 1000)
    js = """
    <script>
    const remaining = __REMAINING__;
    function commit() {
      try {
        const el = window.parent.document.activeElement;
        if (el && el.tagName === 'TEXTAREA') {
          el.blur();
          setTimeout(() => el.focus(), 80);
        }
      } catch (e) {}
    }
    [4000, 2000, 700].forEach(b => {
      const t = remaining - b;
      if (t > 0) setTimeout(commit, t);
    });
    </script>
    """.replace("__REMAINING__", str(remaining_ms))
    components.html(js, height=0)
    typing_fragment()


# ===================================================================
# بخش ۱: راهنمای آزمون
# ===================================================================
if st.session_state.page == "intro":
    st.title("آزمون حافظه اتوبیوگرافیک (AMT)")

    st.markdown("""
    <div class="instruction-card">
        <h3>دستورالعمل آزمون:</h3>
        <p>در این آزمون ما می‌خواهیم بدانیم شما تا چه اندازه می‌توانید <b>خاطرات خاص زندگی خود</b> را به یاد آورید.</p>
        <p>منظور از خاطره، اتفاقی است که در <b>زمان و مکان خاصی</b> اتفاق افتاده و <b>یک روز یا کمتر از یک روز</b> طول کشیده است.</p>
        <ul>
            <li>این خاطره می‌تواند مربوط به <b>روزهای اخیر یا زمان‌های گذشته</b> باشد.</li>
            <li>این خاطره می‌تواند یک اتفاق <b>مهم یا کاملاً عادی</b> در زندگی باشد.</li>
            <li>برای هر لغت باید <b>فقط یک خاطره</b> تعریف کنید.</li>
            <li>خاطره نباید برای لغت‌های مختلف <b>تکرار شود</b>.</li>
        </ul>
        <p><b>روند زمان‌بندی:</b></p>
        <ul>
            <li>برای یادآوری هر کلمه حداکثر <b>۳۰ ثانیه</b> فرصت دارید.</li>
            <li>به محض اینکه خاطره‌ای به ذهنتان آمد، سریعاً روی دکمه <b>«خاطره به ذهنم آمد / شروع تایپ»</b> کلیک کنید.</li>
            <li>اگر در مدت ۳۰ ثانیه خاطره‌ای به یاد نیاوردید، سیستم به‌طور خودکار کلمه بعدی را نمایش می‌دهد.</li>
            <li>پس از کلیک روی دکمه، کلمه مخفی شده و <b>۶۰ ثانیه</b> فرصت تایپ خواهید داشت.</li>
            <li>اگر در ۶۰ ثانیه دکمه «ثبت» را نزنید، هر مقدار که تایپ کرده‌اید به‌طور خودکار ذخیره می‌شود.</li>
        </ul>
        <div class="example-card">
            <b>مثال:</b> کلمه <b>«معلم»</b> را مشاهده می‌کنید. به محض یادآوری دکمه را می‌زنید و خاطره خاص خود را تایپ می‌کنید:<br>
            <i>«سال گذشته روز معلم، معلممان از هدیه‌ای که من به او دادم خیلی خوشش آمد و من را بوسید.»</i>
        </div>
    </div>
    """, unsafe_allow_html=True)

    subject_input = st.text_input("لطفاً کد / شناسه شرکت‌کننده را وارد کنید:")

    if st.button("شروع آزمون"):
        if not subject_input.strip():
            st.error("لطفاً ابتدا شناسه شرکت‌کننده را وارد کنید.")
        else:
            st.session_state.subject_id = subject_input.strip()
            st.session_state.page = "amt_task"
            st.session_state.phase = "viewing"
            st.session_state.phase_start_time = time.time()
            st.rerun()

# ===================================================================
# بخش ۲: اجرای آزمون
# ===================================================================
elif st.session_state.page == "amt_task":
    total_words = len(st.session_state.amt_words)
    current_idx = st.session_state.word_index

    if current_idx >= total_words:
        st.session_state.page = "thank_you"
        st.rerun()
    else:
        st.caption(f"کلمه {current_idx + 1} از {total_words}")
        if st.session_state.phase == "viewing":
            viewing_screen()
        else:
            typing_screen()

# ===================================================================
# بخش ۳: پایان آزمون
# ===================================================================
elif st.session_state.page == "thank_you":
    st.header("پایان آزمون")
    st.balloons()
    st.success("پاسخ‌ها و زمان‌های ثبت خاطرات شما با موفقیت ذخیره شد. سپاسگزاریم.")
    if st.session_state.save_errors:
        st.warning("ذخیره آنلاین برخی پاسخ‌ها با مشکل مواجه شد. لطفاً به پژوهشگر اطلاع دهید.")
        with st.expander("جزئیات فنی (برای پژوهشگر)"):
            for e in st.session_state.save_errors:
                st.code(e)
