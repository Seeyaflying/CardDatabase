import db
import card_manager
db.init_db()
card_manager.reorganize_done_cards()
db.close()
