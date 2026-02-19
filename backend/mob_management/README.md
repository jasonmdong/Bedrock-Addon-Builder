Fields:
mob_name
mob_description
mob_keywords
mob_geometry 
mob_embedding


SQL table: 
mob_geometries (
    mob_id SERIAL PRIMARY KEY,       x
    mob_name VARCHAR(255) NOT NULL,  x
    mob_description TEXT,            x
    prompt TEXT,                     x
    mob_keywords TEXT[],
    mob_geometry JSONB NOT NULL,
    mob_embedding vector(1536)
    bone_metadate JSONB
    complexity_score INT
    is_official BOOLEAN
    creation_date TIMESTAMP 

);

INSERT INTO mob_geometries (mob_name, mob_description, mob_keywords, mob_geometry)
VALUES (...)

https://github.com/Mojang/bedrock-samples/tree/main/resource_pack/models/entity