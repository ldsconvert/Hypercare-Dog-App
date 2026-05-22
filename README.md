# Hypercare Pet Dashboard 🐾

A simple Streamlit app that turns your Hypercare metrics into a fun **cyber pet** + an **exec-ready dashboard**.

## What it uses (from your workbooks)
- Hypercare workbook sheet: **Adoption Report**
- Hypercare workbook sheet: **Hypercare Tasks**
- Metric pack sheet (optional): **Hypercare Interface Report**
- ServiceNow export (optional): **CSV** with a State/Status column

## Quick start
1. Install Python 3.10+.
2. In a terminal:
   - `pip install -r requirements.txt`
3. Run:
   - `streamlit run app.py`

## How to use
- Upload your Excel files in the left sidebar.
- Upload your ServiceNow CSV export (optional) to populate the Tickets tab.
- Use **Feed / Play / Rest / Daily check-in** to make the pet feel alive.

## Notes
- The app does **not** directly connect to ServiceNow.
- It’s designed for minimal coding: upload files + go.
