import re


def _natural_sort_key(code: str):
    import re as _re
    parts = _re.split(r"(\d+)", code)
    result = []
    for p in parts:
        if p.isdigit():
            result.append(int(p))
        elif p:
            result.append(p.lower())
    return result


INDICATOR_TREE = {
    "indicator_group": "SRMNH Inpatient Indicators",
    "code": "SRMNH_25",
    "children": [
        {
            "id": "0",
            "name": "Main elements complete ratio",
            "children": []
        },
        {
            "id": "2",
            "name": "Total Deliveries",
            "children": [
                {
                    "id": "2.a",
                    "name": "Primigravida",
                    "children": []
                },
                {
                    "id": "2.b",
                    "name": "Multigravida",
                    "children": []
                },
                {
                    "id": "2.c",
                    "name": "Age 10-14",
                    "children": []
                },
                {
                    "id": "2.d",
                    "name": "Age 15-19",
                    "children": []
                },
                {
                    "id": "2.e",
                    "name": "Age 20-24",
                    "children": []
                },
                {
                    "id": "2.f",
                    "name": "Age 25-29",
                    "children": []
                },
                {
                    "id": "2.g",
                    "name": "Age 30-34",
                    "children": []
                },
                {
                    "id": "2.h",
                    "name": "Age 35-39",
                    "children": []
                },
                {
                    "id": "2.i",
                    "name": "Age 40-44",
                    "children": []
                },
                {
                    "id": "2.j",
                    "name": "Age 45+",
                    "children": []
                },
                {
                    "id": "2.k",
                    "name": "In-facility deliveries",
                    "children": []
                },
                {
                    "id": "2.l",
                    "name": "Out-of-facility deliveries",
                    "children": []
                },
                {
                    "id": "2.m",
                    "name": "Low risk deliveries",
                    "children": []
                },
                {
                    "id": "2.n",
                    "name": "High risk deliveries",
                    "children": []
                }
            ]
        },
        {
            "id": "3",
            "name": "Normal Vaginal Deliveries",
            "children": []
        },
        {
            "id": "4",
            "name": "Assisted Vaginal Deliveries",
            "children": []
        },
        {
            "id": "5",
            "name": "Caesarean Sections",
            "children": [
                {
                    "id": "5.b.1",
                    "name": "Emergency C/S",
                    "children": []
                },
                {
                    "id": "5.b.2",
                    "name": "Planned C/S",
                    "children": []
                },
                {
                    "id": "5.c",
                    "name": "Primary C/S",
                    "children": []
                },
                {
                    "id": "5.d",
                    "name": "Repeat C/S",
                    "children": []
                }
            ]
        },
        {
            "id": "6",
            "name": "Live Births",
            "children": [
                {
                    "id": "6.a",
                    "name": "Male",
                    "children": []
                },
                {
                    "id": "6.b",
                    "name": "Female",
                    "children": []
                },
                {
                    "id": "6.c",
                    "name": "Unknown sex",
                    "children": []
                },
                {
                    "id": "6.d",
                    "name": "Multiple pregnancy",
                    "children": []
                },
                {
                    "id": "6.e",
                    "name": "Number of twins/multiples",
                    "children": []
                },
                {
                    "id": "6.f",
                    "name": "Preterm births",
                    "children": []
                },
                {
                    "id": "6.g",
                    "name": "Low birth weight",
                    "children": []
                }
            ]
        },
        {
            "id": "7",
            "name": "Fetal Deaths >24 weeks",
            "children": [
                {
                    "id": "7.a",
                    "name": "Fresh stillbirth",
                    "children": []
                },
                {
                    "id": "7.b",
                    "name": "Macerated stillbirth",
                    "children": []
                }
            ]
        },
        {
            "id": "8",
            "name": "Abortions ≤24 weeks",
            "children": [
                {
                    "id": "8.a",
                    "name": "First trimester",
                    "children": []
                },
                {
                    "id": "8.b",
                    "name": "Second trimester",
                    "children": []
                }
            ]
        },
        {
            "id": "9",
            "name": "Congenital Anomalies",
            "children": []
        },
        {
            "id": "10",
            "name": "Severe Maternal Morbidity (SMM)",
            "children": [
                {
                    "id": "10.a",
                    "name": "Hemorrhage",
                    "children": [
                        {
                            "id": "10.a.1",
                            "name": "Postpartum hemorrhage",
                            "children": [
                                {
                                    "id": "10.a.1.1",
                                    "name": "Primary severe",
                                    "children": []
                                },
                                {
                                    "id": "10.a.1.2",
                                    "name": "Secondary severe",
                                    "children": []
                                }
                            ]
                        },
                        {
                            "id": "10.a.2",
                            "name": "Antepartum hemorrhage",
                            "children": [
                                {
                                    "id": "10.a.2.1",
                                    "name": "Placental abruption",
                                    "children": []
                                },
                                {
                                    "id": "10.a.2.2",
                                    "name": "Placenta previa/accreta",
                                    "children": []
                                }
                            ]
                        },
                        {
                            "id": "10.a.3",
                            "name": "Early pregnancy hemorrhage",
                            "children": [
                                {
                                    "id": "10.a.3.1",
                                    "name": "Ectopic pregnancy",
                                    "children": []
                                },
                                {
                                    "id": "10.a.3.2",
                                    "name": "Severe abortion bleeding",
                                    "children": []
                                },
                                {
                                    "id": "10.a.3.3",
                                    "name": "Molar pregnancy",
                                    "children": []
                                }
                            ]
                        },
                        {
                            "id": "10.a.5",
                            "name": "Non-obstetric bleeding",
                            "children": []
                        },
                        {
                            "id": "10.a.6",
                            "name": "Uterine inversion/other",
                            "children": []
                        }
                    ]
                },
                {
                    "id": "10.b",
                    "name": "Uterine rupture",
                    "children": []
                },
                {
                    "id": "10.c",
                    "name": "Relaparotomy",
                    "children": []
                },
                {
                    "id": "10.d",
                    "name": "Hysterectomy",
                    "children": []
                },
                {
                    "id": "10.e",
                    "name": "Hypertensive disorders",
                    "children": [
                        {
                            "id": "10.e.1",
                            "name": "Severe pre-eclampsia",
                            "children": []
                        },
                        {
                            "id": "10.e.2",
                            "name": "HELLP syndrome",
                            "children": []
                        },
                        {
                            "id": "10.e.3",
                            "name": "Eclampsia",
                            "children": []
                        }
                    ]
                },
                {
                    "id": "10.f",
                    "name": "Sepsis",
                    "children": []
                },
                {
                    "id": "10.g",
                    "name": "Respiratory failure/ICU ventilation",
                    "children": []
                },
                {
                    "id": "10.h",
                    "name": "Cardiac ICU admission",
                    "children": []
                },
                {
                    "id": "10.i",
                    "name": "Renal failure/dialysis",
                    "children": []
                },
                {
                    "id": "10.j",
                    "name": "Thromboembolism",
                    "children": [
                        {
                            "id": "10.j.1",
                            "name": "Pulmonary embolism",
                            "children": []
                        },
                        {
                            "id": "10.j.2",
                            "name": "Confirmed embolism",
                            "children": []
                        },
                        {
                            "id": "10.j.3",
                            "name": "Amniotic fluid embolism",
                            "children": []
                        }
                    ]
                },
                {
                    "id": "10.k",
                    "name": "Neurological complications",
                    "children": []
                },
                {
                    "id": "10.l",
                    "name": "Anaesthesia complications",
                    "children": []
                },
                {
                    "id": "10.m",
                    "name": "Unplanned ICU admission",
                    "children": []
                },
                {
                    "id": "10.n",
                    "name": "Self-harm/suicide attempt",
                    "children": []
                },
                {
                    "id": "10.o",
                    "name": "Surgical complications (urinary/bowel)",
                    "children": []
                }
            ]
        },
        {
            "id": "11",
            "name": "Maternal Deaths",
            "children": [
                {
                    "id": "11.a",
                    "name": "In-hospital deaths",
                    "children": []
                },
                {
                    "id": "11.b",
                    "name": "Referred cases",
                    "children": []
                },
                {
                    "id": "11.c",
                    "name": "Community deaths",
                    "children": []
                }
            ]
        },
        {
            "id": "12",
            "name": "ICU admission for obstetric causes",
            "children": []
        },
        {
            "id": "13",
            "name": "Breastfeeding within first hour",
            "children": []
        },
        {
            "id": "14",
            "name": "STIs treated cases",
            "children": []
        },
        {
            "id": "16",
            "name": "NICU admissions",
            "children": []
        },
        {
            "id": "17",
            "name": "Neonatal deaths",
            "children": [
                {
                    "id": "17.a",
                    "name": "Early neonatal death",
                    "children": []
                },
                {
                    "id": "17.b",
                    "name": "Late neonatal death",
                    "children": []
                },
                {
                    "id": "17.c",
                    "name": "Prematurity-related",
                    "children": [
                        {
                            "id": "RDS",
                            "name": "Respiratory distress syndrome",
                            "children": []
                        },
                        {
                            "id": "Sepsis_preterm",
                            "name": "Preterm sepsis",
                            "children": []
                        }
                    ]
                },
                {
                    "id": "17.d",
                    "name": "Birth asphyxia",
                    "children": []
                },
                {
                    "id": "17.e",
                    "name": "Congenital anomalies",
                    "children": []
                },
                {
                    "id": "17.f",
                    "name": "Neonatal sepsis",
                    "children": []
                },
                {
                    "id": "17.g",
                    "name": "Respiratory distress",
                    "children": []
                },
                {
                    "id": "17.h",
                    "name": "Other causes",
                    "children": []
                }
            ]
        },
        {
            "id": "18",
            "name": "Neonatal referrals outside Gaza",
            "children": []
        },
        {
            "id": "19",
            "name": "Sexual and Gender-Based Violence (SGBV) / New survivor cases",
            "children": []
        },
        {
            "id": "20",
            "name": "Emergency contraception (≤5 days)",
            "children": []
        },
        {
            "id": "21",
            "name": "New cases (duplicate registry category)",
            "children": []
        },
        {
            "id": "22",
            "name": "Pregnancy termination ≤40 days",
            "children": []
        },
        {
            "id": "23",
            "name": "Pregnancy termination 40–120 days",
            "children": []
        },
        {
            "id": "24",
            "name": "Forensic evidence collection",
            "children": []
        },
        {
            "id": "25",
            "name": "Psychosocial referral services",
            "children": []
        },
        {
            "id": "26",
            "name": "Died immediately after birth",
            "children": []
        }
    ]
}



def _flatten_tree(node, parent_id=None, result=None):
    if result is None:
        result = []
    code = str(node["id"])
    children = node.get("children") or []
    is_parent = len(children) > 0
    result.append({
        "code": code,
        "name": node["name"],
        "parent_id": parent_id,
        "level": _get_level(code),
        "is_parent": is_parent,
    })
    for child in children:
        _flatten_tree(child, code, result)
    return result


INDICATOR_FLAT_LIST = [
  {
    "code": "0",
    "name": "Main elements complete ratio",
    "parent_id": None,
    "level": 0,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "2",
    "name": "Total Deliveries",
    "parent_id": None,
    "level": 0,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "2.a",
    "name": "Primigravida",
    "parent_id": "2",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "2.b",
    "name": "Multigravida",
    "parent_id": "2",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "2.c",
    "name": "Age 10-14",
    "parent_id": "2",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "2.d",
    "name": "Age 15-19",
    "parent_id": "2",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "2.e",
    "name": "Age 20-24",
    "parent_id": "2",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "2.f",
    "name": "Age 25-29",
    "parent_id": "2",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "2.g",
    "name": "Age 30-34",
    "parent_id": "2",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "2.h",
    "name": "Age 35-39",
    "parent_id": "2",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "2.i",
    "name": "Age 40-44",
    "parent_id": "2",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "2.j",
    "name": "Age 45+",
    "parent_id": "2",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "2.k",
    "name": "In-facility deliveries",
    "parent_id": "2",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "2.l",
    "name": "Out-of-facility deliveries",
    "parent_id": "2",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "2.m",
    "name": "Low risk deliveries",
    "parent_id": "2",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "2.n",
    "name": "High risk deliveries",
    "parent_id": "2",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "3",
    "name": "Normal Vaginal Deliveries",
    "parent_id": None,
    "level": 0,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "4",
    "name": "Assisted Vaginal Deliveries",
    "parent_id": None,
    "level": 0,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "5",
    "name": "Caesarean Sections",
    "parent_id": None,
    "level": 0,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "5.b.1",
    "name": "Emergency C/S",
    "parent_id": "5",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "5.b.2",
    "name": "Planned C/S",
    "parent_id": "5",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "5.c",
    "name": "Primary C/S",
    "parent_id": "5",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "5.d",
    "name": "Repeat C/S",
    "parent_id": "5",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "6",
    "name": "Live Births",
    "parent_id": None,
    "level": 0,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "6.a",
    "name": "Male",
    "parent_id": "6",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "6.b",
    "name": "Female",
    "parent_id": "6",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "6.c",
    "name": "Unknown sex",
    "parent_id": "6",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "6.d",
    "name": "Multiple pregnancy",
    "parent_id": "6",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "6.e",
    "name": "Number of twins/multiples",
    "parent_id": "6",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "6.f",
    "name": "Preterm births",
    "parent_id": "6",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "6.g",
    "name": "Low birth weight",
    "parent_id": "6",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "7",
    "name": "Fetal Deaths >24 weeks",
    "parent_id": None,
    "level": 0,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "7.a",
    "name": "Fresh stillbirth",
    "parent_id": "7",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "7.b",
    "name": "Macerated stillbirth",
    "parent_id": "7",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "8",
    "name": "Abortions ≤24 weeks",
    "parent_id": None,
    "level": 0,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "8.a",
    "name": "First trimester",
    "parent_id": "8",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "8.b",
    "name": "Second trimester",
    "parent_id": "8",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "9",
    "name": "Congenital Anomalies",
    "parent_id": None,
    "level": 0,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10",
    "name": "Severe Maternal Morbidity (SMM)",
    "parent_id": None,
    "level": 0,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.a",
    "name": "Hemorrhage",
    "parent_id": "10",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.a.1",
    "name": "Postpartum hemorrhage",
    "parent_id": "10.a",
    "level": 2,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.a.1.1",
    "name": "Primary severe",
    "parent_id": "10.a.1",
    "level": 3,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.a.1.2",
    "name": "Secondary severe",
    "parent_id": "10.a.1",
    "level": 3,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.a.2",
    "name": "Antepartum hemorrhage",
    "parent_id": "10.a",
    "level": 2,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.a.2.1",
    "name": "Placental abruption",
    "parent_id": "10.a.2",
    "level": 3,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.a.2.2",
    "name": "Placenta previa/accreta",
    "parent_id": "10.a.2",
    "level": 3,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.a.3",
    "name": "Early pregnancy hemorrhage",
    "parent_id": "10.a",
    "level": 2,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.a.3.1",
    "name": "Ectopic pregnancy",
    "parent_id": "10.a.3",
    "level": 3,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.a.3.2",
    "name": "Severe abortion bleeding",
    "parent_id": "10.a.3",
    "level": 3,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.a.3.3",
    "name": "Molar pregnancy",
    "parent_id": "10.a.3",
    "level": 3,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.a.5",
    "name": "Non-obstetric bleeding",
    "parent_id": "10.a",
    "level": 2,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.a.6",
    "name": "Uterine inversion/other",
    "parent_id": "10.a",
    "level": 2,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.b",
    "name": "Uterine rupture",
    "parent_id": "10",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.c",
    "name": "Relaparotomy",
    "parent_id": "10",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.d",
    "name": "Hysterectomy",
    "parent_id": "10",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.e",
    "name": "Hypertensive disorders",
    "parent_id": "10",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.e.1",
    "name": "Severe pre-eclampsia",
    "parent_id": "10.e",
    "level": 2,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.e.2",
    "name": "HELLP syndrome",
    "parent_id": "10.e",
    "level": 2,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.e.3",
    "name": "Eclampsia",
    "parent_id": "10.e",
    "level": 2,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.f",
    "name": "Sepsis",
    "parent_id": "10",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.g",
    "name": "Respiratory failure/ICU ventilation",
    "parent_id": "10",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.h",
    "name": "Cardiac ICU admission",
    "parent_id": "10",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.i",
    "name": "Renal failure/dialysis",
    "parent_id": "10",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.j",
    "name": "Thromboembolism",
    "parent_id": "10",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.j.1",
    "name": "Pulmonary embolism",
    "parent_id": "10.j",
    "level": 2,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.j.2",
    "name": "Confirmed embolism",
    "parent_id": "10.j",
    "level": 2,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.j.3",
    "name": "Amniotic fluid embolism",
    "parent_id": "10.j",
    "level": 2,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.k",
    "name": "Neurological complications",
    "parent_id": "10",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.l",
    "name": "Anaesthesia complications",
    "parent_id": "10",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.m",
    "name": "Unplanned ICU admission",
    "parent_id": "10",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.n",
    "name": "Self-harm/suicide attempt",
    "parent_id": "10",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "10.o",
    "name": "Surgical complications (urinary/bowel)",
    "parent_id": "10",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "11",
    "name": "Maternal Deaths",
    "parent_id": None,
    "level": 0,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "11.a",
    "name": "In-hospital deaths",
    "parent_id": "11",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "11.b",
    "name": "Referred cases",
    "parent_id": "11",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "11.c",
    "name": "Community deaths",
    "parent_id": "11",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "12",
    "name": "ICU admission for obstetric causes",
    "parent_id": None,
    "level": 0,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "13",
    "name": "Breastfeeding within first hour",
    "parent_id": None,
    "level": 0,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "14",
    "name": "STIs treated cases",
    "parent_id": None,
    "level": 0,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "16",
    "name": "NICU admissions",
    "parent_id": None,
    "level": 0,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "17",
    "name": "Neonatal deaths",
    "parent_id": None,
    "level": 0,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "17.a",
    "name": "Early neonatal death",
    "parent_id": "17",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "17.b",
    "name": "Late neonatal death",
    "parent_id": "17",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "17.c",
    "name": "Prematurity-related",
    "parent_id": "17",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "RDS",
    "name": "Respiratory distress syndrome",
    "parent_id": "17.c",
    "level": 2,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "Sepsis_preterm",
    "name": "Preterm sepsis",
    "parent_id": "17.c",
    "level": 2,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "17.d",
    "name": "Birth asphyxia",
    "parent_id": "17",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "17.e",
    "name": "Congenital anomalies",
    "parent_id": "17",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "17.f",
    "name": "Neonatal sepsis",
    "parent_id": "17",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "17.g",
    "name": "Respiratory distress",
    "parent_id": "17",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "17.h",
    "name": "Other causes",
    "parent_id": "17",
    "level": 1,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "18",
    "name": "Neonatal referrals outside Gaza",
    "parent_id": None,
    "level": 0,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "19",
    "name": "Sexual and Gender-Based Violence (SGBV) / New survivor cases",
    "parent_id": None,
    "level": 0,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "20",
    "name": "Emergency contraception (≤5 days)",
    "parent_id": None,
    "level": 0,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "21",
    "name": "New cases (duplicate registry category)",
    "parent_id": None,
    "level": 0,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "22",
    "name": "Pregnancy termination ≤40 days",
    "parent_id": None,
    "level": 0,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "23",
    "name": "Pregnancy termination 40–120 days",
    "parent_id": None,
    "level": 0,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "24",
    "name": "Forensic evidence collection",
    "parent_id": None,
    "level": 0,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "25",
    "name": "Psychosocial referral services",
    "parent_id": None,
    "level": 0,
    "group_name": "SRMNH Inpatient Indicators"
  },
  {
    "code": "26",
    "name": "Died immediately after birth",
    "parent_id": None,
    "level": 0,
    "group_name": "SRMNH Inpatient Indicators"
  }
]


PARENT_CHILD_MAP = {
  "2": [
    "2.a",
    "2.b",
    "2.c",
    "2.d",
    "2.e",
    "2.f",
    "2.g",
    "2.h",
    "2.i",
    "2.j",
    "2.k",
    "2.l",
    "2.m",
    "2.n"
  ],
  "5": [
    "5.b.1",
    "5.b.2",
    "5.c",
    "5.d"
  ],
  "6": [
    "6.a",
    "6.b",
    "6.c",
    "6.d",
    "6.e",
    "6.f",
    "6.g"
  ],
  "7": [
    "7.a",
    "7.b"
  ],
  "8": [
    "8.a",
    "8.b"
  ],
  "10": [
    "10.a",
    "10.b",
    "10.c",
    "10.d",
    "10.e",
    "10.f",
    "10.g",
    "10.h",
    "10.i",
    "10.j",
    "10.k",
    "10.l",
    "10.m",
    "10.n",
    "10.o"
  ],
  "10.a": [
    "10.a.1",
    "10.a.2",
    "10.a.3",
    "10.a.5",
    "10.a.6"
  ],
  "10.a.1": [
    "10.a.1.1",
    "10.a.1.2"
  ],
  "10.a.2": [
    "10.a.2.1",
    "10.a.2.2"
  ],
  "10.a.3": [
    "10.a.3.1",
    "10.a.3.2",
    "10.a.3.3"
  ],
  "10.e": [
    "10.e.1",
    "10.e.2",
    "10.e.3"
  ],
  "10.j": [
    "10.j.1",
    "10.j.2",
    "10.j.3"
  ],
  "11": [
    "11.a",
    "11.b",
    "11.c"
  ],
  "17": [
    "17.a",
    "17.b",
    "17.c",
    "17.d",
    "17.e",
    "17.f",
    "17.g",
    "17.h"
  ],
  "17.c": [
    "RDS",
    "Sepsis_preterm"
  ]
}


INDICATOR_CODE_TO_NAME = {
  "0": "Main elements complete ratio",
  "2": "Total Deliveries",
  "2.a": "Primigravida",
  "2.b": "Multigravida",
  "2.c": "Age 10-14",
  "2.d": "Age 15-19",
  "2.e": "Age 20-24",
  "2.f": "Age 25-29",
  "2.g": "Age 30-34",
  "2.h": "Age 35-39",
  "2.i": "Age 40-44",
  "2.j": "Age 45+",
  "2.k": "In-facility deliveries",
  "2.l": "Out-of-facility deliveries",
  "2.m": "Low risk deliveries",
  "2.n": "High risk deliveries",
  "3": "Normal Vaginal Deliveries",
  "4": "Assisted Vaginal Deliveries",
  "5": "Caesarean Sections",
  "5.b.1": "Emergency C/S",
  "5.b.2": "Planned C/S",
  "5.c": "Primary C/S",
  "5.d": "Repeat C/S",
  "6": "Live Births",
  "6.a": "Male",
  "6.b": "Female",
  "6.c": "Unknown sex",
  "6.d": "Multiple pregnancy",
  "6.e": "Number of twins/multiples",
  "6.f": "Preterm births",
  "6.g": "Low birth weight",
  "7": "Fetal Deaths >24 weeks",
  "7.a": "Fresh stillbirth",
  "7.b": "Macerated stillbirth",
  "8": "Abortions ≤24 weeks",
  "8.a": "First trimester",
  "8.b": "Second trimester",
  "9": "Congenital Anomalies",
  "10": "Severe Maternal Morbidity (SMM)",
  "10.a": "Hemorrhage",
  "10.a.1": "Postpartum hemorrhage",
  "10.a.1.1": "Primary severe",
  "10.a.1.2": "Secondary severe",
  "10.a.2": "Antepartum hemorrhage",
  "10.a.2.1": "Placental abruption",
  "10.a.2.2": "Placenta previa/accreta",
  "10.a.3": "Early pregnancy hemorrhage",
  "10.a.3.1": "Ectopic pregnancy",
  "10.a.3.2": "Severe abortion bleeding",
  "10.a.3.3": "Molar pregnancy",
  "10.a.5": "Non-obstetric bleeding",
  "10.a.6": "Uterine inversion/other",
  "10.b": "Uterine rupture",
  "10.c": "Relaparotomy",
  "10.d": "Hysterectomy",
  "10.e": "Hypertensive disorders",
  "10.e.1": "Severe pre-eclampsia",
  "10.e.2": "HELLP syndrome",
  "10.e.3": "Eclampsia",
  "10.f": "Sepsis",
  "10.g": "Respiratory failure/ICU ventilation",
  "10.h": "Cardiac ICU admission",
  "10.i": "Renal failure/dialysis",
  "10.j": "Thromboembolism",
  "10.j.1": "Pulmonary embolism",
  "10.j.2": "Confirmed embolism",
  "10.j.3": "Amniotic fluid embolism",
  "10.k": "Neurological complications",
  "10.l": "Anaesthesia complications",
  "10.m": "Unplanned ICU admission",
  "10.n": "Self-harm/suicide attempt",
  "10.o": "Surgical complications (urinary/bowel)",
  "11": "Maternal Deaths",
  "11.a": "In-hospital deaths",
  "11.b": "Referred cases",
  "11.c": "Community deaths",
  "12": "ICU admission for obstetric causes",
  "13": "Breastfeeding within first hour",
  "14": "STIs treated cases",
  "16": "NICU admissions",
  "17": "Neonatal deaths",
  "17.a": "Early neonatal death",
  "17.b": "Late neonatal death",
  "17.c": "Prematurity-related",
  "RDS": "Respiratory distress syndrome",
  "Sepsis_preterm": "Preterm sepsis",
  "17.d": "Birth asphyxia",
  "17.e": "Congenital anomalies",
  "17.f": "Neonatal sepsis",
  "17.g": "Respiratory distress",
  "17.h": "Other causes",
  "18": "Neonatal referrals outside Gaza",
  "19": "Sexual and Gender-Based Violence (SGBV) / New survivor cases",
  "20": "Emergency contraception (≤5 days)",
  "21": "New cases (duplicate registry category)",
  "22": "Pregnancy termination ≤40 days",
  "23": "Pregnancy termination 40–120 days",
  "24": "Forensic evidence collection",
  "25": "Psychosocial referral services",
  "26": "Died immediately after birth"
}


INDICATOR_NAME_TO_CODE = {
  "Main elements complete ratio": "0",
  "Total Deliveries": "2",
  "Primigravida": "2.a",
  "Multigravida": "2.b",
  "Age 10-14": "2.c",
  "Age 15-19": "2.d",
  "Age 20-24": "2.e",
  "Age 25-29": "2.f",
  "Age 30-34": "2.g",
  "Age 35-39": "2.h",
  "Age 40-44": "2.i",
  "Age 45+": "2.j",
  "In-facility deliveries": "2.k",
  "Out-of-facility deliveries": "2.l",
  "Low risk deliveries": "2.m",
  "High risk deliveries": "2.n",
  "Normal Vaginal Deliveries": "3",
  "Assisted Vaginal Deliveries": "4",
  "Caesarean Sections": "5",
  "Emergency C/S": "5.b.1",
  "Planned C/S": "5.b.2",
  "Primary C/S": "5.c",
  "Repeat C/S": "5.d",
  "Live Births": "6",
  "Male": "6.a",
  "Female": "6.b",
  "Unknown sex": "6.c",
  "Multiple pregnancy": "6.d",
  "Number of twins/multiples": "6.e",
  "Preterm births": "6.f",
  "Low birth weight": "6.g",
  "Fetal Deaths >24 weeks": "7",
  "Fresh stillbirth": "7.a",
  "Macerated stillbirth": "7.b",
  "Abortions ≤24 weeks": "8",
  "First trimester": "8.a",
  "Second trimester": "8.b",
  "Congenital Anomalies": "9",
  "Severe Maternal Morbidity (SMM)": "10",
  "Hemorrhage": "10.a",
  "Postpartum hemorrhage": "10.a.1",
  "Primary severe": "10.a.1.1",
  "Secondary severe": "10.a.1.2",
  "Antepartum hemorrhage": "10.a.2",
  "Placental abruption": "10.a.2.1",
  "Placenta previa/accreta": "10.a.2.2",
  "Early pregnancy hemorrhage": "10.a.3",
  "Ectopic pregnancy": "10.a.3.1",
  "Severe abortion bleeding": "10.a.3.2",
  "Molar pregnancy": "10.a.3.3",
  "Non-obstetric bleeding": "10.a.5",
  "Uterine inversion/other": "10.a.6",
  "Uterine rupture": "10.b",
  "Relaparotomy": "10.c",
  "Hysterectomy": "10.d",
  "Hypertensive disorders": "10.e",
  "Severe pre-eclampsia": "10.e.1",
  "HELLP syndrome": "10.e.2",
  "Eclampsia": "10.e.3",
  "Sepsis": "10.f",
  "Respiratory failure/ICU ventilation": "10.g",
  "Cardiac ICU admission": "10.h",
  "Renal failure/dialysis": "10.i",
  "Thromboembolism": "10.j",
  "Pulmonary embolism": "10.j.1",
  "Confirmed embolism": "10.j.2",
  "Amniotic fluid embolism": "10.j.3",
  "Neurological complications": "10.k",
  "Anaesthesia complications": "10.l",
  "Unplanned ICU admission": "10.m",
  "Self-harm/suicide attempt": "10.n",
  "Surgical complications (urinary/bowel)": "10.o",
  "Maternal Deaths": "11",
  "In-hospital deaths": "11.a",
  "Referred cases": "11.b",
  "Community deaths": "11.c",
  "ICU admission for obstetric causes": "12",
  "Breastfeeding within first hour": "13",
  "STIs treated cases": "14",
  "NICU admissions": "16",
  "Neonatal deaths": "17",
  "Early neonatal death": "17.a",
  "Late neonatal death": "17.b",
  "Prematurity-related": "17.c",
  "Respiratory distress syndrome": "RDS",
  "Preterm sepsis": "Sepsis_preterm",
  "Birth asphyxia": "17.d",
  "Congenital anomalies": "17.e",
  "Neonatal sepsis": "17.f",
  "Respiratory distress": "17.g",
  "Other causes": "17.h",
  "Neonatal referrals outside Gaza": "18",
  "Sexual and Gender-Based Violence (SGBV) / New survivor cases": "19",
  "Emergency contraception (≤5 days)": "20",
  "New cases (duplicate registry category)": "21",
  "Pregnancy termination ≤40 days": "22",
  "Pregnancy termination 40–120 days": "23",
  "Forensic evidence collection": "24",
  "Psychosocial referral services": "25",
  "Died immediately after birth": "26"
}



def _get_level(code: str) -> int:
    dots = str(code).count(".")
    return dots


def get_all_indicators():
    return [item["code"] for item in INDICATOR_FLAT_LIST]


def build_tree_from_db(session):
    from app.models import Indicator
    indicators = session.query(Indicator).order_by(Indicator.sort_order, Indicator.code).all()
    ind_map = {ind.id: ind for ind in indicators}
    children_map = {}
    root_ids = []
    for ind in indicators:
        if ind.parent_id is None:
            root_ids.append(ind.id)
        else:
            children_map.setdefault(ind.parent_id, []).append(ind.id)

    def _build_node(ind_id):
        ind = ind_map[ind_id]
        children = sorted(
            (_build_node(cid) for cid in children_map.get(ind_id, [])),
            key=lambda n: _natural_sort_key(n["id"]),
        )
        node = {
            "id": ind.code,
            "name": ind.name,
            "children": list(children),
        }
        return node

    tree = {
        "indicator_group": "SRMNH Inpatient Indicators",
        "code": "SRMNH_25",
        "children": [_build_node(rid) for rid in root_ids],
    }
    return tree


def get_flat_list_from_db(session):
    from app.models import Indicator
    indicators = session.query(Indicator).order_by(Indicator.sort_order, Indicator.code).all()
    ind_map = {ind.id: ind for ind in indicators}
    result = []
    for ind in indicators:
        parent_code = None
        if ind.parent_id and ind.parent_id in ind_map:
            parent_code = ind_map[ind.parent_id].code
        result.append({
            "code": ind.code,
            "name": ind.name,
            "parent_id": parent_code,
            "level": ind.level,
            "group_name": ind.group_name or "SRMNH Inpatient Indicators",
        })
    return result