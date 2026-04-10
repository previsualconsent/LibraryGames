-- Initialize the database.
-- Drop any existing data and create empty tables.

DROP TABLE IF EXISTS user;

DROP TABLE IF EXISTS library;
DROP TABLE IF EXISTS bgg;
DROP TABLE IF EXISTS list;
DROP TABLE IF EXISTS list_game;
DROP TABLE IF EXISTS refresh_job;

CREATE TABLE user (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  password TEXT NOT NULL
);

CREATE TABLE library (
  id INTEGER PRIMARY KEY,
  bgg_id INT,
  name TEXT NOT NULL,
  added date NOT NULL default CURRENT_DATE,
  url TEXT NOT NULL,
  FOREIGN KEY (bgg_id) REFERENCES bgg (id)
);

CREATE TABLE bgg (
  id INT PRIMARY KEY,
  gamep TEXT,
  updated date default NULL
);

CREATE TABLE list (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE (user_id, name),
  FOREIGN KEY (user_id) REFERENCES user (id)
);

CREATE TABLE list_game (
  list_id INTEGER NOT NULL,
  game_id INTEGER NOT NULL,
  PRIMARY KEY (list_id, game_id),
  FOREIGN KEY (list_id) REFERENCES list (id),
  FOREIGN KEY (game_id) REFERENCES library (id)
);

CREATE TABLE refresh_job (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_by INTEGER NOT NULL,
  status TEXT NOT NULL,
  message TEXT,
  error TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  started_at TIMESTAMP,
  finished_at TIMESTAMP,
  FOREIGN KEY (created_by) REFERENCES user (id)
);

CREATE INDEX idx_list_user_id ON list (user_id);
CREATE INDEX idx_list_game_list_id ON list_game (list_id);
CREATE INDEX idx_refresh_job_user_created ON refresh_job (created_by, created_at DESC);
