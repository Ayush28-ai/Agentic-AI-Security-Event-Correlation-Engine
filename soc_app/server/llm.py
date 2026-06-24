import uvicorn
from fastapi import FastAPI
from sqlalchemy import Column , Integer , String , create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Item(Base):
    __tablename__ = "item"
    id = Column(Integer , primary_key=True , index = True)
    name  = Column(String)
    description = Column(String)
Base.metadata.create_all(engine)
app = FastAPI(title = "sql")
@app.post("/item")
async def create_item(name , description):
    db = SessionLocal()
    db_item = Item(name = name , description = description)
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    return db_item

@app.get("/item/{id}")
async def read_item(id: int):
    db = SessionLocal()
    item = db.query(Item).filter(Item.id == id).first()
    return item

@app.put("/item/{id}")
async def update_item(id: int, name , description):
    db = SessionLocal()
    item = db.query(Item).filter(Item.id == id).first()
    item.name = name
    item.description = description
    db.commit()
    return item
@app.delete("/item/{id}")
async def delete_item(id: int):
    db = SessionLocal()
    item = db.query(Item).filter(Item.id == id).first()
    db.delete(item)
    db.commit()
    return {"message":" item deleted succesfully"}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9000)



