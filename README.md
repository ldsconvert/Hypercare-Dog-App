# Inventory Hound Dashboard 🐶

One dog per product. Upload a **BOTF PI Daily** PDF and the app parses the PRIMA/ULTRA summary rows.

## What it looks for in the PDF
It scans for product rows like **PRIMA 60**, **PRIMA 100**, **PRIMA 220**, **PRIMA 600**, **ULTRA 4**, **ULTRA 6** in the summary section.

## How the dogs work
- **Happiness** is driven by Days of Inventory (Avail Inv Days)
- **Hunger** is driven by capacity % (low % = hungry, high % = overfull)
- **Energy** blends happiness + hunger + available room days

## Run locally
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy on Streamlit
Upload these files to your GitHub repo:
- app.py
- requirements.txt
- README.md

Then deploy in Streamlit Community Cloud.
