-- Showroom Soundcheck - Database Initialization
-- Reflex/SQLModel handles table creation via Alembic migrations,
-- but this file ensures the database and extensions are ready.

-- Enable useful extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Grant permissions (Reflex will create tables via alembic)
-- This is a safety net in case the app needs manual table creation.
