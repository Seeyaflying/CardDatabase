import db
import card_manager
db.init_db()
card_manager.verify()
db.close()
