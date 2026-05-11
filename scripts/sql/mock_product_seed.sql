-- Auto-generated seed data for the mock product schema
BEGIN;
TRUNCATE TABLE s_data, s_data_current, waterBalance, dataDefinition, consumer_profile, assetProperties, assets, data_sources, districtInfo, district, region, operationArea, facilityType, measurementPointType, measurementType RESTART IDENTITY CASCADE;

INSERT INTO measurementType (id, name, deletable, showInMnfChart, groupId, hasReverseColors) VALUES
    (1, 'flow', TRUE, TRUE, 10, FALSE),
    (2, 'pressure', TRUE, FALSE, 10, TRUE),
    (3, 'level', TRUE, FALSE, 20, FALSE),
    (4, 'consumption', TRUE, FALSE, 30, FALSE),
    (5, 'leakage', TRUE, FALSE, 30, TRUE);

INSERT INTO measurementPointType (id, name) VALUES
    (1, 'reservoir_sensor'),
    (2, 'dma_meter'),
    (3, 'pump_sensor'),
    (4, 'consumer_meter'),
    (5, 'valve_sensor');

INSERT INTO facilityType (id, name) VALUES
    (1, 'reservoir'),
    (2, 'pump_station'),
    (3, 'metering_station'),
    (4, 'dma'),
    (5, 'chamber');

INSERT INTO operationArea (opAreaId, name, area, population, lengthOfMainNetwork, numberOfConsumers, validFrom, gisId, color) VALUES
    (201, 'North Operations', 82.5, 125000, 410.2, 38200, '2025-01-01 00:00:00', 'OA-NORTH-201', '#1f6f8b'),
    (202, 'West Operations', 61.3, 88000, 295.4, 25400, '2025-01-01 00:00:00', 'OA-WEST-202', '#355070');

INSERT INTO region (id, name, city, area, population, validFrom, gisId, color) VALUES
    (1, 'North Region', 'DemoCity', 112.4, 145000, '2025-01-01 00:00:00', 'REG-NORTH-1', '#264653'),
    (2, 'West Region', 'DemoCity', 94.9, 101000, '2025-01-01 00:00:00', 'REG-WEST-2', '#2a9d8f');

INSERT INTO district (id, name) VALUES
    (11, 'Riverside'),
    (12, 'Hilltop');

INSERT INTO districtInfo (id, name, region, area, population, lengthOfMainNetwork, numberOfConsumers, validFrom, gisId, color) VALUES
    (101, 'Riverside DMA', 1, 25.6, 42000, 130.4, 12100, '2025-01-01 00:00:00', 'DMA-RIVER-101', '#e76f51'),
    (102, 'Hilltop DMA', 2, 18.2, 28600, 96.8, 8400, '2025-01-01 00:00:00', 'DMA-HILL-102', '#f4a261');

INSERT INTO data_sources (id, name, type, config, enabled, created_at, updated_at) VALUES
    (1, 'SCADA OPC-UA', 'opcua', '{"endpoint": "opc.tcp://demo-water.local:4840", "site": "north"}'::jsonb, TRUE, '2026-01-10 08:00:00', '2026-05-10 09:15:00'),
    (2, 'Pressure MQTT Feed', 'mqtt', '{"broker": "mqtt://demo-water.local:1883", "topic": "pressure/+"}'::jsonb, TRUE, '2026-01-10 08:10:00', '2026-05-10 09:15:00'),
    (3, 'Formula Engine', 'formula', '{"engine": "demo-rules", "refresh_minutes": 15}'::jsonb, TRUE, '2026-01-10 08:20:00', '2026-05-10 09:15:00');

INSERT INTO assets (id, parentId, type, label, gisId, longitude, latitude, measurementPointTypeId, facilityTypeId, opAreaId, region, district, dashboardId, i1, i2, f1, s1, color, validFrom) VALUES
    (1101, NULL, 'reservoir', 'North Reservoir A', 'AST-1101', 29.1024, 41.0187, 1, 1, 201, 1, 101, NULL, NULL, NULL, 18.7, 'critical_storage', '#457b9d', '2025-01-01 00:00:00'),
    (1201, 1101, 'DMA', 'Riverside DMA Inlet', 'AST-1201', 29.1091, 41.0205, 2, 4, 201, 1, 101, NULL, 1, NULL, 0.94, 'north_dma', '#e63946', '2025-01-01 00:00:00'),
    (1301, 1101, 'pump', 'East Pump Station', 'AST-1301', 29.1132, 41.0248, 3, 2, 201, 1, 101, NULL, 2, NULL, 3.0, 'booster', '#1d3557', '2025-01-01 00:00:00'),
    (1401, 1201, 'valve', 'Valve Chamber 7', 'AST-1401', 29.1114, 41.0199, 5, 5, 201, 1, 101, NULL, NULL, NULL, NULL, 'manual_asset', '#6d597a', '2025-01-01 00:00:00'),
    (1501, NULL, 'DMA', 'Hilltop DMA Inlet', 'AST-1501', 29.0715, 40.9984, 2, 4, 202, 2, 102, NULL, 1, NULL, 0.91, 'west_dma', '#f77f00', '2025-01-01 00:00:00'),
    (1601, 1201, 'meter', 'Consumer Meter Block A', 'AST-1601', 29.1107, 41.0218, 4, 3, 201, 1, 101, NULL, NULL, NULL, NULL, 'consumer_meter', '#8d99ae', '2025-01-01 00:00:00');

INSERT INTO assetProperties (id, assetId, i1, i2, f1, f2, d1, d2) VALUES
    (1, 1101, 2, NULL, 12500.0, 8400.0, '2025-03-15 00:00:00', '2026-04-20 00:00:00'),
    (2, 1201, 15, NULL, 1.2, 0.8, '2025-02-01 00:00:00', '2026-05-01 00:00:00'),
    (3, 1501, 15, NULL, 1.0, 0.7, '2025-02-01 00:00:00', '2026-05-01 00:00:00');

INSERT INTO consumer_profile (profileId, name, type, template_id, asset_id) VALUES
    (701, 'Residential Midrise', 'residential', NULL, 1601);

INSERT INTO dataDefinition (id, register, label, archivePeriod, isActive, measurementTypeId, assetId, description, unit, type, formula, showCurrentValues, opAreaId, regionId, districtId, isPrimary, isDefault, showInMap, availability, automaticCreated, dataSourceId) VALUES
    (2001, 'REG_FLOW_DMA_RIVERSIDE', 'Riverside Inlet Flow', '15m', TRUE, 1, 1201, 'Primary DMA inflow meter', 'm3/h', 'telemetry', NULL, TRUE, 201, 1, 101, TRUE, TRUE, TRUE, 0.995, FALSE, 1),
    (2002, 'REG_PRESS_DMA_RIVERSIDE', 'Riverside Pressure', '15m', TRUE, 2, 1201, 'District pressure sensor', 'bar', 'telemetry', NULL, TRUE, 201, 1, 101, TRUE, TRUE, TRUE, 0.989, FALSE, 2),
    (2003, 'REG_LEVEL_RES_NORTH', 'North Reservoir Level', '15m', TRUE, 3, 1101, 'Reservoir level sensor', 'm', 'telemetry', NULL, TRUE, 201, 1, 101, TRUE, TRUE, TRUE, 0.998, FALSE, 1),
    (2004, 'REG_CONS_DMA_RIVERSIDE', 'Riverside Billed Consumption', '1d', TRUE, 4, 1601, 'Aggregated billed demand', 'm3/d', 'derived', 'SUM(zone_consumption)', TRUE, 201, 1, 101, FALSE, TRUE, FALSE, 0.971, TRUE, 3),
    (2005, 'REG_LEAK_DMA_RIVERSIDE', 'Riverside Estimated Leakage', '1d', TRUE, 5, 1201, 'Estimated leakage KPI', 'm3/d', 'derived', 'input-consumption-authorized', TRUE, 201, 1, 101, FALSE, FALSE, TRUE, 0.96, TRUE, 3),
    (2006, 'REG_FLOW_DMA_HILLTOP', 'Hilltop Inlet Flow', '15m', TRUE, 1, 1501, 'Primary DMA inflow meter', 'm3/h', 'telemetry', NULL, TRUE, 202, 2, 102, TRUE, TRUE, TRUE, 0.991, FALSE, 1),
    (2007, 'REG_PRESS_DMA_HILLTOP', 'Hilltop Pressure', '15m', TRUE, 2, 1501, 'District pressure sensor', 'bar', 'telemetry', NULL, TRUE, 202, 2, 102, TRUE, TRUE, TRUE, 0.984, FALSE, 2),
    (2008, 'REG_FLOW_PUMP_EAST', 'East Pump Station Flow', '15m', FALSE, 1, 1301, 'Disabled meter for maintenance demo', 'm3/h', 'telemetry', NULL, FALSE, 201, 1, 101, FALSE, FALSE, FALSE, 0.54, FALSE, 1);

INSERT INTO waterBalance (id, assetId, interval, systemInputId, billMeteredId, billUnmeteredId, unbillMetered, unbillUnmetered, unauthConsumption, customerInacuracy, leakageNetwork, leakageReservoir, leakageService, isDefault, recordDate, createdAt, updatedAt) VALUES
    (3001, 1201, '1d', 2001, 2004, NULL, 8.5, 3.1, 1.4, 2.7, 14.8, 0.9, 4.2, TRUE, '2026-05-10 00:00:00', '2026-05-10 05:00:00', '2026-05-10 05:00:00'),
    (3002, 1501, '1d', 2006, NULL, NULL, 5.2, 2.0, 0.8, 1.8, 9.7, 0.5, 2.9, TRUE, '2026-05-10 00:00:00', '2026-05-10 05:10:00', '2026-05-10 05:10:00');

INSERT INTO s_data_current (dataid, interval, type, ze1, ze2, value, id, art, quality) VALUES
    ('REG_FLOW_DMA_RIVERSIDE', '15m', 'telemetry', '2026-05-11 08:00:00', '2026-05-11 08:15:00', 182.4, 9001, 'avg', 'good'),
    ('REG_PRESS_DMA_RIVERSIDE', '15m', 'telemetry', '2026-05-11 08:00:00', '2026-05-11 08:15:00', 4.8, 9002, 'avg', 'good'),
    ('REG_LEVEL_RES_NORTH', '15m', 'telemetry', '2026-05-11 08:00:00', '2026-05-11 08:15:00', 7.2, 9003, 'avg', 'good'),
    ('REG_CONS_DMA_RIVERSIDE', '1d', 'derived', '2026-05-10 00:00:00', '2026-05-11 00:00:00', 3520.0, 9004, 'sum', 'estimated'),
    ('REG_LEAK_DMA_RIVERSIDE', '1d', 'derived', '2026-05-10 00:00:00', '2026-05-11 00:00:00', 621.0, 9005, 'sum', 'estimated'),
    ('REG_FLOW_DMA_HILLTOP', '15m', 'telemetry', '2026-05-11 08:00:00', '2026-05-11 08:15:00', 143.1, 9006, 'avg', 'good'),
    ('REG_PRESS_DMA_HILLTOP', '15m', 'telemetry', '2026-05-11 08:00:00', '2026-05-11 08:15:00', 4.3, 9007, 'avg', 'good');

INSERT INTO s_data (id, ze1, ze2, dataid, value, interval, art, type, quality, created_at) VALUES
    (9101, '2026-05-10 00:00:00', '2026-05-10 00:15:00', 'REG_FLOW_DMA_RIVERSIDE', 176.3, '15m', 'avg', 'telemetry', 'good', '2026-05-10 00:16:00'),
    (9102, '2026-05-10 00:15:00', '2026-05-10 00:30:00', 'REG_FLOW_DMA_RIVERSIDE', 178.9, '15m', 'avg', 'telemetry', 'good', '2026-05-10 00:31:00'),
    (9103, '2026-05-10 00:30:00', '2026-05-10 00:45:00', 'REG_FLOW_DMA_RIVERSIDE', 181.7, '15m', 'avg', 'telemetry', 'good', '2026-05-10 00:46:00'),
    (9104, '2026-05-10 00:00:00', '2026-05-10 00:15:00', 'REG_PRESS_DMA_RIVERSIDE', 4.6, '15m', 'avg', 'telemetry', 'good', '2026-05-10 00:16:00'),
    (9105, '2026-05-10 00:15:00', '2026-05-10 00:30:00', 'REG_PRESS_DMA_RIVERSIDE', 4.7, '15m', 'avg', 'telemetry', 'good', '2026-05-10 00:31:00'),
    (9106, '2026-05-10 00:30:00', '2026-05-10 00:45:00', 'REG_PRESS_DMA_RIVERSIDE', 4.8, '15m', 'avg', 'telemetry', 'good', '2026-05-10 00:46:00'),
    (9107, '2026-05-10 00:00:00', '2026-05-10 00:15:00', 'REG_LEVEL_RES_NORTH', 7.6, '15m', 'avg', 'telemetry', 'good', '2026-05-10 00:16:00'),
    (9108, '2026-05-10 00:15:00', '2026-05-10 00:30:00', 'REG_LEVEL_RES_NORTH', 7.4, '15m', 'avg', 'telemetry', 'good', '2026-05-10 00:31:00'),
    (9109, '2026-05-10 00:30:00', '2026-05-10 00:45:00', 'REG_LEVEL_RES_NORTH', 7.3, '15m', 'avg', 'telemetry', 'good', '2026-05-10 00:46:00'),
    (9110, '2026-05-10 00:00:00', '2026-05-10 00:15:00', 'REG_FLOW_DMA_HILLTOP', 139.8, '15m', 'avg', 'telemetry', 'good', '2026-05-10 00:16:00'),
    (9111, '2026-05-10 00:15:00', '2026-05-10 00:30:00', 'REG_FLOW_DMA_HILLTOP', 141.2, '15m', 'avg', 'telemetry', 'good', '2026-05-10 00:31:00'),
    (9112, '2026-05-10 00:30:00', '2026-05-10 00:45:00', 'REG_FLOW_DMA_HILLTOP', 142.6, '15m', 'avg', 'telemetry', 'good', '2026-05-10 00:46:00'),
    (9113, '2026-05-10 00:00:00', '2026-05-11 00:00:00', 'REG_CONS_DMA_RIVERSIDE', 3520.0, '1d', 'sum', 'derived', 'estimated', '2026-05-11 00:05:00'),
    (9114, '2026-05-10 00:00:00', '2026-05-11 00:00:00', 'REG_LEAK_DMA_RIVERSIDE', 621.0, '1d', 'sum', 'derived', 'estimated', '2026-05-11 00:05:00'),
    (9115, '2026-05-10 00:00:00', '2026-05-10 00:15:00', 'REG_PRESS_DMA_HILLTOP', 4.1, '15m', 'avg', 'telemetry', 'good', '2026-05-10 00:16:00'),
    (9116, '2026-05-10 00:15:00', '2026-05-10 00:30:00', 'REG_PRESS_DMA_HILLTOP', 4.2, '15m', 'avg', 'telemetry', 'good', '2026-05-10 00:31:00'),
    (9117, '2026-05-10 00:30:00', '2026-05-10 00:45:00', 'REG_PRESS_DMA_HILLTOP', 4.3, '15m', 'avg', 'telemetry', 'good', '2026-05-10 00:46:00');

UPDATE assets
SET i2 = 701
WHERE id = 1601;

COMMIT;
