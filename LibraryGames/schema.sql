-- Initialize the database.
-- Drop any existing data and create empty tables.

DROP TABLE IF EXISTS user;

DROP TABLE IF EXISTS library;
DROP TABLE IF EXISTS bgg;
DROP TABLE IF EXISTS list;
DROP TABLE IF EXISTS list_game;

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

CREATE TABLE list_game (
  game_id INT,
  list_name TEXT,
  FOREIGN KEY (game_id) REFERENCES library (id)
);
