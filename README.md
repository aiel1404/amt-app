# آزمون حافظه اتوبیوگرافیک (AMT) – Streamlit

## اجرای محلی
```bash
pip install -r requirements.txt
cp .streamlit/secrets.toml.example .streamlit/secrets.toml   # و مقادیر را پر کنید
streamlit run app.py
```

## اتصال به Google Sheets
1. در Google Cloud یک پروژه بسازید و **Google Sheets API** و **Google Drive API** را فعال کنید.
2. یک Service Account بسازید و کلید JSON آن را دانلود کنید.
3. یک Google Sheet بسازید و با `client_email` سرویس‌اکانت، دسترسی **Editor** بدهید.
4. مقادیر JSON و آدرس شیت را در `.streamlit/secrets.toml` بگذارید.

## اتصال به GitHub و دیپلوی
```bash
git init
git add .
git commit -m "AMT app"
git branch -M main
git remote add origin https://github.com/USERNAME/REPO.git
git push -u origin main
```
سپس در https://share.streamlit.io با GitHub وارد شوید، New app را بزنید، ریپو و `app.py` را انتخاب کنید و در Advanced settings > Secrets محتوای secrets.toml را بچسبانید.

⚠️ ریپو را **Private** بگیرید و هرگز `secrets.toml` یا فایل CSV داده‌ها را commit نکنید.
