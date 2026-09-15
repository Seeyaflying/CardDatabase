import db
import card_manager
db.init_db()
card_manager.archive_only()
db.close()
