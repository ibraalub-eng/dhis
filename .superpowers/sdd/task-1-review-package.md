# Task 1 Review Package

## Commits
7a36ff7 feat: add FacilityOwnership, FacilityType models and schemas

## Diff Stats
 app/models.py  | 23 +++++++++++++++++++++++
 app/schemas.py | 32 ++++++++++++++++++++++++++++++++
 2 files changed, 55 insertions(+)

## Full Diff
```
diff --git a/app/models.py b/app/models.py
index 14bb58f..e403b08 100644
--- a/app/models.py
+++ b/app/models.py
@@ -17,40 +17,63 @@ class Governorate(Base):
 class HospitalType(Base):
     __tablename__ = "hospital_types"
 
     id = Column(Integer, primary_key=True, index=True)
     name = Column(String(255), unique=True, nullable=False, index=True)
     created_at = Column(DateTime, default=datetime.utcnow)
 
     hospitals = relationship("Hospital", back_populates="hospital_type")
 
 
+class FacilityOwnership(Base):
+    __tablename__ = "facility_ownerships"
+
+    id = Column(Integer, primary_key=True, index=True)
+    name = Column(String(255), unique=True, nullable=False)
+    created_at = Column(DateTime, default=datetime.utcnow)
+    hospitals = relationship("Hospital", back_populates="facility_ownership")
+
+
+class FacilityType(Base):
+    __tablename__ = "facility_types"
+
+    id = Column(Integer, primary_key=True, index=True)
+    name = Column(String(255), unique=True, nullable=False)
+    created_at = Column(DateTime, default=datetime.utcnow)
+    hospitals = relationship("Hospital", back_populates="facility_type")
+
+
 class Hospital(Base):
     __tablename__ = "hospitals"
 
     id = Column(Integer, primary_key=True, index=True)
     name = Column(String(255), unique=True, nullable=False, index=True)
     region = Column(String(100), nullable=True)
     governorate_id = Column(Integer, ForeignKey("governorates.id"), nullable=True)
     hospital_type_id = Column(Integer, ForeignKey("hospital_types.id"), nullable=True)
     address = Column(Text, nullable=True)
+    organisation_unit_id = Column(String(100), nullable=True)
+    facility_ownership_id = Column(Integer, ForeignKey("facility_ownerships.id", ondelete="SET NULL"), nullable=True)
+    facility_type_id = Column(Integer, ForeignKey("facility_types.id", ondelete="SET NULL"), nullable=True)
     is_active = Column(Boolean, default=True, index=True)
     created_at = Column(DateTime, default=datetime.utcnow)
 
     indicator_values = relationship("IndicatorValue", back_populates="hospital")
     validation_results = relationship("ValidationResult", back_populates="hospital")
     anomaly_results = relationship("AnomalyResult", back_populates="hospital")
     quality_scores = relationship("QualityScore", back_populates="hospital")
     clinical_insights = relationship("ClinicalInsight", back_populates="hospital")
     indicator_configs = relationship("HospitalIndicatorConfig", back_populates="hospital", cascade="all, delete-orphan")
     governorate = relationship("Governorate", back_populates="hospitals")
     hospital_type = relationship("HospitalType", back_populates="hospitals")
+    facility_ownership = relationship("FacilityOwnership", back_populates="hospitals")
+    facility_type = relationship("FacilityType", back_populates="hospitals")
 
 
 class Indicator(Base):
     __tablename__ = "indicators"
 
     id = Column(Integer, primary_key=True, index=True)
     code = Column(String(50), unique=True, nullable=False, index=True)
     name = Column(String(500), nullable=False)
     parent_id = Column(Integer, ForeignKey("indicators.id"), nullable=True)
     level = Column(Integer, default=0)
diff --git a/app/schemas.py b/app/schemas.py
index 62928f8..dbe9065 100644
--- a/app/schemas.py
+++ b/app/schemas.py
@@ -15,33 +15,38 @@ class PaginatedResponse(BaseModel, Generic[T]):
 class PaginatedParams(BaseModel):
     skip: int = 0
     limit: int = 100
 
 
 class HospitalBase(BaseModel):
     name: str
     region: Optional[str] = None
     governorate_id: Optional[int] = None
     hospital_type_id: Optional[int] = None
+    organisation_unit_id: Optional[str] = None
+    facility_ownership_id: Optional[int] = None
+    facility_type_id: Optional[int] = None
     address: Optional[str] = None
 
 
 class HospitalCreate(HospitalBase):
     pass
 
 
 class HospitalOut(HospitalBase):
     id: int
     is_active: bool = True
     created_at: Optional[datetime] = None
     governorate_name: Optional[str] = None
     hospital_type_name: Optional[str] = None
+    facility_ownership_name: Optional[str] = None
+    facility_type_name: Optional[str] = None
 
     class Config:
         from_attributes = True
 
 
 class GovernorateBase(BaseModel):
     name: str
 
 
 class GovernorateCreate(GovernorateBase):
@@ -65,20 +70,47 @@ class HospitalTypeCreate(HospitalTypeBase):
 
 
 class HospitalTypeOut(HospitalTypeBase):
     id: int
     created_at: Optional[datetime] = None
 
     class Config:
         from_attributes = True
 
 
+class FacilityOwnershipBase(BaseModel):
+    name: str
+
+class FacilityOwnershipCreate(FacilityOwnershipBase):
+    pass
+
+class FacilityOwnershipOut(FacilityOwnershipBase):
+    id: int
+    created_at: Optional[datetime] = None
+
+    class Config:
+        from_attributes = True
+
+class FacilityTypeBase(BaseModel):
+    name: str
+
+class FacilityTypeCreate(FacilityTypeBase):
+    pass
+
+class FacilityTypeOut(FacilityTypeBase):
+    id: int
+    created_at: Optional[datetime] = None
+
+    class Config:
+        from_attributes = True
+
+
 class IndicatorBase(BaseModel):
     code: str
     name: str
     parent_id: Optional[int] = None
     level: int = 0
     sort_order: int = 0
     group_name: Optional[str] = None
 
 
 class IndicatorOut(IndicatorBase):
```
