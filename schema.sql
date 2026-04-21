CREATE TABLE IF NOT EXISTS profiles (
    id UUID PRIMARY KEY,
    name VARCHAR(255) UNIQUE NOT NULL,
    gender VARCHAR(50),
    gender_probability FLOAT,
    age INT,
    age_group VARCHAR(50),
    country_id VARCHAR(2),
    country_name VARCHAR(255),
    country_probability FLOAT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexing for performance
CREATE INDEX IF NOT EXISTS idx_gender ON profiles(gender);
CREATE INDEX IF NOT EXISTS idx_age_group ON profiles(age_group);
CREATE INDEX IF NOT EXISTS idx_country_id ON profiles(country_id);
CREATE INDEX IF NOT EXISTS idx_age ON profiles(age);
