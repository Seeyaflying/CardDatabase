from v1.Utilities import db
import card_manager
db.init_db()
card_manager.rebuild_index()
db.close()
