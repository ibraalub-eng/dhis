import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models import Governorate, HospitalType, FacilityOwnership, FacilityType, Hospital

DATA = [
    (1026, "وزارة الصحة/مستشفيات/مستشفى العيون", "حكومي", "مستشفيات", "مستشفى تخصصي", None),
    (1023, "مستشفيات/ مستشفى الصليب الأحمر الميداني/ ICRC", "INGOs", "مستشفيات", "مستشفى ميداني", "محافظة خان يونس"),
    (1007, "جمعية الوفاء/مستشفيات/مستشفى الوفاء للتأهيل الطبي", "NGOs", "مستشفيات", "مستشفى تخصصي", None),
    (2162, "جمعية السلام/مستشفيات/مستشفى دارالسلام", "NGOs", "مستشفيات", "مستشفى عام", None),
    (1022, "وزارة الصحة/مستشفيات/مستشفى الشفاء", "حكومي", "مستشفيات", "مستشفى عام", "محافظة غزة"),
    (1025, "العودة/مستشفيات/مستشفى العودة-النصيرات", "NGOs", "مستشفيات", "مستشفى عام", "محافظة الوسطى"),
    (1017, "وزارة الصحة/مستشفيات/مستشفى الاندونيسي", "حكومي", "مستشفيات", "مستشفى عام", None),
    (1020, "الخدمة العامة/ مستشفيات/ مستشفى الخدمة العامة", "NGOs", "مستشفيات", "مستشفى عام", None),
    (1015, "مستشفيات/ مستشفى أطباء بلا حدود الميداني- هولندا/MSF", "INGOs", "مستشفيات", "مستشفى ميداني", None),
    (1021, "وزارة الصحة/مستشفيات/مستشفى الزوايدة الميداني", "حكومي", "مستشفيات", "مستشفى ميداني", None),
    (1027, "وزارة الصحة/مستشفيات/عبدالعزيز الرنتيسي", "حكومي", "مستشفيات", "مستشفى تخصصي", "محافظة غزة"),
    (45290, "وزارة الصحة / مستشفيات/مستشفى الدرة", "حكومي", "مستشفيات", "مستشفى تخصصي", None),
    (1016, "الكنيسة الانجليكانية/مستشفيات/مستشفى الأهلي العربي", "NGOs", "مستشفيات", "مستشفى عام", "محافظة غزة"),
    (48134, "قطر للتنمية/مستشفيات/مستشفى حمد للتأهيل والأطراف الصناعية", "NGOs", "مستشفيات", "مستشفى تخصصي", None),
    (1005, "مستشفيات/المستشفى البريطاني الميداني/ Uk-Med", "INGOs", "مستشفيات", "مستشفى ميداني", "محافظة خان يونس"),
    (1032, "الصلاح الإسلامية/ مستشفيات/مستشفى يافا", "NGOs", "مستشفيات", "مستشفى عام", None),
    (46941, "الهلال الأحمر/مستشفيات/مستشفى السرايا الميداني", "NGOs", "مستشفيات", "مستشفى ميداني", None),
    (1028, "وزارة الصحة/مستشفيات/مستشفى شهداء الأقصى", "حكومي", "مستشفيات", "مستشفى عام", "محافظة الوسطى"),
    (26212, "الخدمات الأردنية/مستشفيات/الميداني الأردني", "INGOs", "مستشفيات", "مستشفى ميداني", None),
    (15106, "جمعية مركز حيفا/مستشفيات /مستشفى حيفا", "NGOs", "مستشفيات", "مستشفى عام", None),
    (1009, "الصحابة/مستشفيات/مجمع الصحابة الطبي", "NGOs", "مستشفيات", "مستشفى عام", "محافظة غزة"),
    (1030, "مستشفيات / مستشفى مدينة الأمل/ PRCS", "NGOs", "مستشفيات", "مستشفى عام", "محافظة خان يونس"),
    (102944, "وزارة الصحة/مستشفيات/مستشفى الشفاء-الحلو", "حكومي", "مستشفيات", "مستشفى عام", None),
    (102946, "وزارة الصحة/مستشفيات/مستشفى الشفاء-الخدمة العامة", "حكومي", "مستشفيات", "مستشفى عام", None),
    (99164, "الخدمات الأردنية/مستشفيات/الميداني الأردني خانيونس", "INGOs", "مستشفيات", "مستشفى ميداني", "محافظة خان يونس"),
    (48932, "وزارة الصحة/ مستشفيات /مركز غزة للسرطان", "حكومي", "مستشفيات", "مستشفى تخصصي", None),
    (106895, "مستشفيات / مستشفى المواصي الميداني/ PRCS", "NGOs", "مستشفيات", "مستشفى ميداني", "محافظة خان يونس"),
    (1031, "وزارة الصحة/ مستشفيات/ مستشفى ناصر", "حكومي", "مستشفيات", "مستشفى عام", "محافظة خان يونس"),
    (1008, "الكويتي / مستشفيات/مستشفى الكويت التخصصي الميداني -شفاء فلسطين", "NGOs", "مستشفيات", "مستشفى ميداني", "محافظة خان يونس"),
    (13135, "الصحابة/مستشفيات/مستشفى الخير", "NGOs", "مستشفيات", "مستشفى تخصصي", "محافظة خان يونس"),
    (132799, "مستشفيات/ الهيئة الطبية الدولية الميداني غزة الكتيبة/IMC", "INGOs", "مستشفيات", "مستشفى ميداني", "محافظة غزة"),
    (1024, "العودة/مستشفيات/مستشفى العودة- جباليا", "NGOs", "مستشفيات", "مستشفى عام", "محافظة الشمال"),
    (44641, "مستشفيات/ مستشفي القدس/PRCS", "NGOs", "مستشفيات", "مستشفى عام", "محافظة غزة"),
    (1029, "وزارة الصحة/مستشفيات/مستشفى كمال عدوان", "حكومي", "مستشفيات", "مستشفى عام", "محافظة الشمال"),
    (1018, "وزارة الصحة/مستشفيات/ مستشفى الاوروبي", "حكومي", "مستشفيات", "مستشفى عام", None),
    (12951, "وزارة الصحة/ مستشفيات /مستشفى الهلال الاماراتي", "حكومي", "مستشفيات", "مستشفى عام", None),
    (1019, "الحلو/مستشفيات/ مستشفى الحلوالدولي", "خاص", "مستشفيات", "مستشفى عام", None),
    (1003, "أصدقاء المريض/ مستشفيات/ مستشفى أصدقاء المريض", "NGOs", "مستشفيات", "مستشفى عام", "محافظة غزة"),
    (1004, "مستشفيات/ الهيئة الطبية الدولية الميداني ديرالبلح/IMC", "INGOs", "مستشفيات", "مستشفى ميداني", "محافظة الوسطى"),
    (4877, "مستشفيات/مستشفى القدس الميداني/PRCS", "NGOs", "مستشفيات", "مستشفى ميداني", None),
    (148282, "مستشفى سانت جون للعيون", "NGOs", "مستشفيات", "مستشفى تخصصي", None),
]


def normalize(name):
    return name.strip().replace("\u200f", "").replace("\u200e", "")


def get_or_create(db, model, name):
    if not name:
        return None
    name = normalize(name)
    obj = db.query(model).filter(model.name == name).first()
    if not obj:
        obj = model(name=name)
        db.add(obj)
        db.flush()
    return obj


def run():
    db = SessionLocal()
    seen = set()
    created = 0
    updated = 0
    skipped = 0

    try:
        for org_id, raw_name, ownership, facility_type, hosp_type, gov in DATA:
            name = normalize(raw_name)
            if name in seen:
                skipped += 1
                continue
            seen.add(name)

            owner_obj = get_or_create(db, FacilityOwnership, ownership)
            ft_obj = get_or_create(db, FacilityType, facility_type)
            ht_obj = get_or_create(db, HospitalType, hosp_type)
            gov_obj = get_or_create(db, Governorate, gov)

            hospital = db.query(Hospital).filter(Hospital.name == name).first()
            if hospital:
                hospital.organisation_unit_id = str(org_id)
                hospital.facility_ownership_id = owner_obj.id if owner_obj else None
                hospital.facility_type_id = ft_obj.id if ft_obj else None
                hospital.hospital_type_id = ht_obj.id if ht_obj else None
                hospital.governorate_id = gov_obj.id if gov_obj else None
                updated += 1
            else:
                hospital = Hospital(
                    name=name,
                    organisation_unit_id=str(org_id),
                    facility_ownership_id=owner_obj.id if owner_obj else None,
                    facility_type_id=ft_obj.id if ft_obj else None,
                    hospital_type_id=ht_obj.id if ht_obj else None,
                    governorate_id=gov_obj.id if gov_obj else None,
                    is_active=False,
                )
                db.add(hospital)
                created += 1

        db.commit()
        print(f"Done: {updated} updated, {created} created, {skipped} skipped")
    except Exception as e:
        db.rollback()
        print(f"Error: {e}", file=sys.stderr)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
