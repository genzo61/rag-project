-- Auto-generated from mock-npm-llm-schema.json
BEGIN;
CREATE TABLE IF NOT EXISTS assets (
    id INTEGER NOT NULL,
    parentId INTEGER,
    type TEXT,
    label TEXT,
    gisId TEXT,
    longitude DOUBLE PRECISION,
    latitude DOUBLE PRECISION,
    measurementPointTypeId INTEGER,
    facilityTypeId INTEGER,
    opAreaId INTEGER,
    region INTEGER,
    district INTEGER,
    dashboardId INTEGER,
    i1 INTEGER,
    i2 INTEGER,
    f1 DOUBLE PRECISION,
    s1 TEXT,
    color TEXT,
    validFrom TIMESTAMP,
    PRIMARY KEY (id)
);

-- Skipped unresolved foreign key assets.dashboardId -> dashboard_like_external.id
CREATE TABLE IF NOT EXISTS assetProperties (
    id INTEGER NOT NULL,
    assetId INTEGER NOT NULL,
    i1 INTEGER,
    i2 INTEGER,
    f1 DOUBLE PRECISION,
    f2 DOUBLE PRECISION,
    d1 TIMESTAMP,
    d2 TIMESTAMP,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS dataDefinition (
    id INTEGER NOT NULL,
    register TEXT NOT NULL,
    label TEXT,
    archivePeriod TEXT NOT NULL,
    isActive BOOLEAN,
    measurementTypeId INTEGER,
    assetId INTEGER,
    description TEXT,
    unit TEXT,
    type TEXT NOT NULL,
    formula TEXT,
    showCurrentValues BOOLEAN,
    opAreaId INTEGER,
    regionId INTEGER,
    districtId INTEGER,
    isPrimary BOOLEAN,
    isDefault BOOLEAN,
    showInMap BOOLEAN,
    availability DOUBLE PRECISION,
    automaticCreated BOOLEAN NOT NULL,
    dataSourceId INTEGER,
    PRIMARY KEY (id),
    UNIQUE (register)
);

CREATE TABLE IF NOT EXISTS s_data (
    id BIGINT NOT NULL,
    ze1 TIMESTAMP NOT NULL,
    ze2 TIMESTAMP,
    dataid TEXT,
    value DOUBLE PRECISION,
    interval TEXT,
    art TEXT,
    type TEXT,
    quality TEXT,
    created_at TIMESTAMP,
    PRIMARY KEY (id, ze1)
);

CREATE TABLE IF NOT EXISTS s_data_current (
    dataid TEXT NOT NULL,
    interval TEXT NOT NULL,
    type TEXT NOT NULL,
    ze1 TIMESTAMP,
    ze2 TIMESTAMP,
    value DOUBLE PRECISION,
    id BIGINT,
    art TEXT,
    quality TEXT,
    PRIMARY KEY (dataid, interval, type)
);

CREATE TABLE IF NOT EXISTS measurementType (
    id INTEGER NOT NULL,
    name TEXT,
    deletable BOOLEAN,
    showInMnfChart BOOLEAN,
    groupId INTEGER,
    hasReverseColors BOOLEAN NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS measurementPointType (
    id INTEGER NOT NULL,
    name TEXT,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS facilityType (
    id INTEGER NOT NULL,
    name TEXT,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS operationArea (
    opAreaId INTEGER NOT NULL,
    name TEXT,
    area DOUBLE PRECISION,
    population INTEGER,
    lengthOfMainNetwork DOUBLE PRECISION,
    numberOfConsumers INTEGER,
    validFrom TIMESTAMP,
    gisId TEXT,
    color TEXT,
    PRIMARY KEY (opAreaId)
);

CREATE TABLE IF NOT EXISTS region (
    id INTEGER NOT NULL,
    name TEXT,
    city TEXT,
    area DOUBLE PRECISION,
    population INTEGER,
    validFrom TIMESTAMP,
    gisId TEXT,
    color TEXT,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS district (
    id INTEGER NOT NULL,
    name TEXT,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS districtInfo (
    id INTEGER NOT NULL,
    name TEXT,
    region INTEGER,
    area DOUBLE PRECISION,
    population INTEGER,
    lengthOfMainNetwork DOUBLE PRECISION,
    numberOfConsumers INTEGER,
    validFrom TIMESTAMP,
    gisId TEXT,
    color TEXT,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS data_sources (
    id INTEGER NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    config JSONB NOT NULL,
    enabled BOOLEAN NOT NULL,
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS waterBalance (
    id INTEGER NOT NULL,
    assetId INTEGER NOT NULL,
    interval TEXT NOT NULL,
    systemInputId INTEGER,
    billMeteredId INTEGER,
    billUnmeteredId INTEGER,
    unbillMetered DOUBLE PRECISION NOT NULL,
    unbillUnmetered DOUBLE PRECISION NOT NULL,
    unauthConsumption DOUBLE PRECISION NOT NULL,
    customerInacuracy DOUBLE PRECISION NOT NULL,
    leakageNetwork DOUBLE PRECISION NOT NULL,
    leakageReservoir DOUBLE PRECISION NOT NULL,
    leakageService DOUBLE PRECISION NOT NULL,
    isDefault BOOLEAN NOT NULL,
    recordDate TIMESTAMP,
    createdAt TIMESTAMP NOT NULL,
    updatedAt TIMESTAMP NOT NULL,
    PRIMARY KEY (id)
);

CREATE TABLE IF NOT EXISTS consumer_profile (
    profileId INTEGER NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    template_id INTEGER,
    asset_id INTEGER,
    PRIMARY KEY (profileId)
);

ALTER TABLE assets ADD CONSTRAINT fk_assets_parentid FOREIGN KEY (parentId) REFERENCES assets (id);
ALTER TABLE assets ADD CONSTRAINT fk_assets_measurementpointtypeid FOREIGN KEY (measurementPointTypeId) REFERENCES measurementPointType (id);
ALTER TABLE assets ADD CONSTRAINT fk_assets_facilitytypeid FOREIGN KEY (facilityTypeId) REFERENCES facilityType (id);
ALTER TABLE assets ADD CONSTRAINT fk_assets_opareaid FOREIGN KEY (opAreaId) REFERENCES operationArea (opAreaId);
ALTER TABLE assets ADD CONSTRAINT fk_assets_region FOREIGN KEY (region) REFERENCES region (id);
ALTER TABLE assets ADD CONSTRAINT fk_assets_district FOREIGN KEY (district) REFERENCES districtInfo (id);
ALTER TABLE assets ADD CONSTRAINT fk_assets_i2 FOREIGN KEY (i2) REFERENCES consumer_profile (profileId);
ALTER TABLE assetProperties ADD CONSTRAINT fk_assetproperties_assetid FOREIGN KEY (assetId) REFERENCES assets (id);
ALTER TABLE dataDefinition ADD CONSTRAINT fk_datadefinition_assetid FOREIGN KEY (assetId) REFERENCES assets (id);
ALTER TABLE dataDefinition ADD CONSTRAINT fk_datadefinition_measurementtypeid FOREIGN KEY (measurementTypeId) REFERENCES measurementType (id);
ALTER TABLE dataDefinition ADD CONSTRAINT fk_datadefinition_opareaid FOREIGN KEY (opAreaId) REFERENCES operationArea (opAreaId);
ALTER TABLE dataDefinition ADD CONSTRAINT fk_datadefinition_regionid FOREIGN KEY (regionId) REFERENCES region (id);
ALTER TABLE dataDefinition ADD CONSTRAINT fk_datadefinition_districtid FOREIGN KEY (districtId) REFERENCES districtInfo (id);
ALTER TABLE dataDefinition ADD CONSTRAINT fk_datadefinition_datasourceid FOREIGN KEY (dataSourceId) REFERENCES data_sources (id);
ALTER TABLE s_data ADD CONSTRAINT fk_s_data_dataid FOREIGN KEY (dataid) REFERENCES dataDefinition (register);
ALTER TABLE s_data_current ADD CONSTRAINT fk_s_data_current_dataid FOREIGN KEY (dataid) REFERENCES dataDefinition (register);
ALTER TABLE districtInfo ADD CONSTRAINT fk_districtinfo_region FOREIGN KEY (region) REFERENCES region (id);
ALTER TABLE waterBalance ADD CONSTRAINT fk_waterbalance_assetid FOREIGN KEY (assetId) REFERENCES assets (id);
ALTER TABLE waterBalance ADD CONSTRAINT fk_waterbalance_systeminputid FOREIGN KEY (systemInputId) REFERENCES dataDefinition (id);
ALTER TABLE waterBalance ADD CONSTRAINT fk_waterbalance_billmeteredid FOREIGN KEY (billMeteredId) REFERENCES dataDefinition (id);
ALTER TABLE waterBalance ADD CONSTRAINT fk_waterbalance_billunmeteredid FOREIGN KEY (billUnmeteredId) REFERENCES dataDefinition (id);
ALTER TABLE consumer_profile ADD CONSTRAINT fk_consumer_profile_asset_id FOREIGN KEY (asset_id) REFERENCES assets (id);

CREATE INDEX IF NOT EXISTS idx_assetproperties_assetid ON assetProperties (assetId);
CREATE INDEX IF NOT EXISTS idx_assets_district ON assets (district);
CREATE INDEX IF NOT EXISTS idx_assets_facilitytypeid ON assets (facilityTypeId);
CREATE INDEX IF NOT EXISTS idx_assets_i2 ON assets (i2);
CREATE INDEX IF NOT EXISTS idx_assets_measurementpointtypeid ON assets (measurementPointTypeId);
CREATE INDEX IF NOT EXISTS idx_assets_opareaid ON assets (opAreaId);
CREATE INDEX IF NOT EXISTS idx_assets_parentid ON assets (parentId);
CREATE INDEX IF NOT EXISTS idx_assets_region ON assets (region);
CREATE INDEX IF NOT EXISTS idx_consumer_profile_asset_id ON consumer_profile (asset_id);
CREATE INDEX IF NOT EXISTS idx_datadefinition_assetid ON dataDefinition (assetId);
CREATE INDEX IF NOT EXISTS idx_datadefinition_datasourceid ON dataDefinition (dataSourceId);
CREATE INDEX IF NOT EXISTS idx_datadefinition_districtid ON dataDefinition (districtId);
CREATE INDEX IF NOT EXISTS idx_datadefinition_measurementtypeid ON dataDefinition (measurementTypeId);
CREATE INDEX IF NOT EXISTS idx_datadefinition_opareaid ON dataDefinition (opAreaId);
CREATE INDEX IF NOT EXISTS idx_datadefinition_regionid ON dataDefinition (regionId);
CREATE INDEX IF NOT EXISTS idx_districtinfo_region ON districtInfo (region);
CREATE INDEX IF NOT EXISTS idx_s_data_current_dataid ON s_data_current (dataid);
CREATE INDEX IF NOT EXISTS idx_s_data_dataid ON s_data (dataid);
CREATE INDEX IF NOT EXISTS idx_waterbalance_assetid ON waterBalance (assetId);
CREATE INDEX IF NOT EXISTS idx_waterbalance_billmeteredid ON waterBalance (billMeteredId);
CREATE INDEX IF NOT EXISTS idx_waterbalance_billunmeteredid ON waterBalance (billUnmeteredId);
CREATE INDEX IF NOT EXISTS idx_waterbalance_systeminputid ON waterBalance (systemInputId);

COMMIT;
