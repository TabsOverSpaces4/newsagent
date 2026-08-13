CREATE TABLE IF NOT EXISTS ratings (
  id       INTEGER PRIMARY KEY AUTOINCREMENT,
  story_id TEXT      NOT NULL,
  url      TEXT,
  source   TEXT,
  title    TEXT,
  score    INTEGER   NOT NULL CHECK (score BETWEEN 0 AND 10),
  run_date TEXT,
  rated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_ratings_source   ON ratings (source);
CREATE INDEX IF NOT EXISTS idx_ratings_run_date ON ratings (run_date);
