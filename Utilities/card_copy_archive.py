import db
import card_manager
db.init_db()
card_manager.copy_and_archive()
db.close()
