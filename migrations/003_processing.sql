CREATE TABLE IF NOT EXISTS camroom_processing (
  id text PRIMARY KEY,
  room_code text NOT NULL,
  metadata jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS camroom_processing_room ON camroom_processing(room_code);
