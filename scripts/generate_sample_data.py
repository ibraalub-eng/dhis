"""Generate a sample Excel file for testing."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from app.indicators import INDICATOR_FLAT_LIST


def generate_sample_excel(output_path: str = None, num_hospitals: int = 5):
    if output_path is None:
        output_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "sample", "sample_srmnh_data.xlsx"
        )

    indicator_names = [ind["name"] for ind in INDICATOR_FLAT_LIST]
    hospitals = [
        "Al-Shifa Hospital",
        "European Gaza Hospital",
        "Nasser Medical Complex",
        "Al-Aqsa Martyrs Hospital",
        "Al-Remal Clinic",
    ][:num_hospitals]
    months = ["2026-01", "2026-02", "2026-03", "2026-04"]

    np.random.seed(42)
    rows = []

    for hospital in hospitals:
        for month in months:
            row = {"organisationunitname": hospital, "month": month}
            total_del = int(np.random.randint(150, 400))
            row["Total Deliveries"] = total_del

            primigravida = int(total_del * np.random.uniform(0.25, 0.40))
            row["Primigravida"] = primigravida
            row["Multigravida"] = total_del - primigravida

            row["Age 10-14"] = int(total_del * np.random.uniform(0.001, 0.01))
            row["Age 15-19"] = int(total_del * np.random.uniform(0.05, 0.15))
            row["Age 20-24"] = int(total_del * np.random.uniform(0.20, 0.35))
            row["Age 25-29"] = int(total_del * np.random.uniform(0.20, 0.30))
            row["Age 30-34"] = int(total_del * np.random.uniform(0.10, 0.20))
            row["Age 35-39"] = int(total_del * np.random.uniform(0.05, 0.15))
            row["Age 40-44"] = int(total_del * np.random.uniform(0.01, 0.05))
            row["Age 45+"] = int(total_del * np.random.uniform(0.0, 0.01))

            row["In-facility deliveries"] = int(total_del * np.random.uniform(0.85, 0.98))
            row["Out-of-facility deliveries"] = total_del - row["In-facility deliveries"]
            row["Low risk deliveries"] = int(total_del * np.random.uniform(0.60, 0.80))
            row["High risk deliveries"] = total_del - row["Low risk deliveries"]

            nvd = int(total_del * np.random.uniform(0.55, 0.70))
            row["Normal Vaginal Deliveries"] = nvd
            assisted = int(total_del * np.random.uniform(0.02, 0.08))
            row["Assisted Vaginal Deliveries"] = assisted
            cs = total_del - nvd - assisted
            row["Caesarean Sections"] = max(cs, 0)

            emergency_cs = int(cs * np.random.uniform(0.40, 0.60))
            row["Emergency C/S"] = emergency_cs
            row["Planned C/S"] = cs - emergency_cs
            row["Primary C/S"] = int(cs * np.random.uniform(0.60, 0.80))
            row["Repeat C/S"] = cs - row["Primary C/S"]

            live_births = int(total_del * np.random.uniform(0.95, 1.0))
            row["Live Births"] = live_births
            male_pct = np.random.uniform(0.48, 0.52)
            row["Male"] = int(live_births * male_pct)
            row["Female"] = live_births - row["Male"]
            row["Unknown sex"] = max(int(live_births * 0.001), 0)
            row["Multiple pregnancy"] = int(np.random.randint(2, 10))
            row["Number of twins/multiples"] = row["Multiple pregnancy"] * 2
            row["Preterm births"] = int(live_births * np.random.uniform(0.05, 0.15))
            row["Low birth weight"] = int(live_births * np.random.uniform(0.05, 0.12))

            fetal_deaths = int(np.random.randint(3, 15))
            row["Fetal Deaths >24 weeks"] = fetal_deaths
            row["Fresh stillbirth"] = int(fetal_deaths * np.random.uniform(0.40, 0.60))
            row["Macerated stillbirth"] = fetal_deaths - row["Fresh stillbirth"]

            abortions = int(np.random.randint(5, 25))
            row["Abortions ≤24 weeks"] = abortions
            row["First trimester"] = int(abortions * np.random.uniform(0.60, 0.80))
            row["Second trimester"] = abortions - row["First trimester"]

            row["Congenital Anomalies"] = int(np.random.randint(1, 8))

            smm = int(np.random.randint(5, 30))
            row["Severe Maternal Morbidity (SMM)"] = smm

            hemorrhage = int(smm * np.random.uniform(0.30, 0.50))
            row["Hemorrhage"] = hemorrhage
            pph = int(hemorrhage * np.random.uniform(0.50, 0.70))
            row["Postpartum hemorrhage"] = pph
            row["Primary severe"] = int(pph * np.random.uniform(0.60, 0.80))
            row["Secondary severe"] = pph - row["Primary severe"]
            aph = int(hemorrhage * np.random.uniform(0.10, 0.30))
            row["Antepartum hemorrhage"] = aph
            row["Placental abruption"] = int(aph * np.random.uniform(0.50, 0.70))
            row["Placenta previa/accreta"] = aph - row["Placental abruption"]
            eph = int(hemorrhage * np.random.uniform(0.05, 0.20))
            row["Early pregnancy hemorrhage"] = eph
            row["Ectopic pregnancy"] = int(eph * 0.4)
            row["Severe abortion bleeding"] = int(eph * 0.4)
            row["Molar pregnancy"] = eph - row["Ectopic pregnancy"] - row["Severe abortion bleeding"]
            row["Non-obstetric bleeding"] = max(hemorrhage - pph - aph - eph, 0)
            row["Uterine inversion/other"] = max(int(np.random.randint(0, 2)), 0)

            row["Uterine rupture"] = int(np.random.randint(0, 3))
            row["Relaparotomy"] = int(np.random.randint(0, 2))
            row["Hysterectomy"] = int(np.random.randint(0, 3))

            hypertensive = int(smm * np.random.uniform(0.15, 0.30))
            row["Hypertensive disorders"] = hypertensive
            row["Severe pre-eclampsia"] = int(hypertensive * 0.50)
            row["HELLP syndrome"] = int(hypertensive * 0.20)
            row["Eclampsia"] = hypertensive - row["Severe pre-eclampsia"] - row["HELLP syndrome"]

            row["Sepsis"] = int(np.random.randint(1, 5))
            row["Respiratory failure/ICU ventilation"] = int(np.random.randint(0, 4))
            row["Cardiac ICU admission"] = int(np.random.randint(0, 2))
            row["Renal failure/dialysis"] = int(np.random.randint(0, 2))

            thrombo = int(np.random.randint(0, 3))
            row["Thromboembolism"] = thrombo
            row["Pulmonary embolism"] = max(int(thrombo * 0.4), 0)
            row["Confirmed embolism"] = max(int(thrombo * 0.3), 0)
            row["Amniotic fluid embolism"] = max(thrombo - row["Pulmonary embolism"] - row["Confirmed embolism"], 0)

            row["Neurological complications"] = int(np.random.randint(0, 3))
            row["Anaesthesia complications"] = int(np.random.randint(0, 2))
            row["Unplanned ICU admission"] = int(np.random.randint(1, 10))
            row["Self-harm/suicide attempt"] = int(np.random.randint(0, 1))
            row["Surgical complications (urinary/bowel)"] = int(np.random.randint(0, 2))

            maternal_deaths = int(np.random.randint(0, 3))
            row["Maternal Deaths"] = maternal_deaths
            row["In-hospital deaths"] = int(maternal_deaths * np.random.uniform(0.50, 0.80))
            row["Referred cases"] = int(np.random.randint(0, 2))
            row["Community deaths"] = max(maternal_deaths - row["In-hospital deaths"] - row["Referred cases"], 0)

            row["Breastfeeding within first hour"] = int(live_births * np.random.uniform(0.50, 0.80))
            row["STIs treated cases"] = int(np.random.randint(10, 50))
            row["NICU admissions"] = int(live_births * np.random.uniform(0.05, 0.15))

            neo_deaths = int(np.random.randint(3, 15))
            row["Neonatal deaths"] = neo_deaths
            early_nd = int(neo_deaths * np.random.uniform(0.60, 0.80))
            row["Early neonatal death"] = early_nd
            row["Late neonatal death"] = neo_deaths - early_nd
            row["Prematurity-related"] = int(neo_deaths * np.random.uniform(0.20, 0.40))
            row["Respiratory distress syndrome"] = int(row["Prematurity-related"] * 0.5)
            row["Preterm sepsis"] = row["Prematurity-related"] - row["Respiratory distress syndrome"]
            row["Birth asphyxia"] = int(neo_deaths * np.random.uniform(0.15, 0.30))
            row["Congenital anomalies"] = int(neo_deaths * np.random.uniform(0.05, 0.15))

            remaining_nd = neo_deaths - row["Prematurity-related"] - row["Birth asphyxia"] - row["Congenital anomalies"]
            row["Neonatal sepsis"] = max(int(remaining_nd * 0.4), 0)
            row["Respiratory distress"] = max(int(remaining_nd * 0.3), 0)
            row["Other causes"] = max(remaining_nd - row["Neonatal sepsis"] - row["Respiratory distress"], 0)

            row["Neonatal referrals outside Gaza"] = int(np.random.randint(2, 15))

            sgbv = int(np.random.randint(5, 30))
            row["Sexual and Gender-Based Violence (SGBV)"] = sgbv
            row["New survivor cases"] = int(sgbv * 0.8)
            row["Emergency contraception (≤5 days)"] = int(sgbv * 0.5)
            row["New cases (duplicate registry category)"] = int(sgbv * 0.3)
            row["Pregnancy termination ≤40 days"] = int(np.random.randint(1, 10))
            row["Pregnancy termination 40–120 days"] = int(np.random.randint(0, 5))
            row["Forensic evidence collection"] = int(np.random.randint(0, 8))
            row["Psychosocial referral services"] = int(sgbv * 0.6)

            rows.append(row)

    df = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    from openpyxl import Workbook
    from openpyxl.utils.dataframe import dataframe_to_rows

    wb = Workbook()
    ws = wb.active
    ws.title = "SRMNH Data"

    for month_str in months:
        ws.append([f"Monthly Report - {month_str}"])
        ws.append([])
        break

    header_row_idx = ws.max_row + 1
    cols = ["organisationunitname", "month"] + indicator_names
    ws.append(cols)

    for r in rows:
        row_data = [r.get("organisationunitname", r.get("hospital_name", ""))]
        row_data.append(r.get("month", ""))
        row_data.extend([r.get(name, None) for name in indicator_names])
        ws.append(row_data)

    wb.save(output_path)
    print(f"Sample Excel created at: {output_path}")
    print(f"  {len(rows)} rows, {len(cols)} columns")
    print(f"  Title row with month, blank row, then headers on row 3")
    return output_path


if __name__ == "__main__":
    generate_sample_excel()