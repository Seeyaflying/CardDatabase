import db
import card_manager
db.init_db()
card_manager.scan_for_new_cards()
db.close()
