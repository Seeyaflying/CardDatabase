import db
import card_manager
db.init_db()
card_manager.clean_empty_folders()
db.close()
