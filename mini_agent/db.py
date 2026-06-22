"""Mini Agent 数据库层 —— ORM 版（SQLAlchemy Declarative）。"""
import os
from sqlalchemy import create_engine,String
from sqlalchemy.orm import Session,DeclarativeBase,Mapped,mapped_column

DB_PATH = os.path.join(os.path.dirname(__file__), "employees.db")
engine = create_engine(f"sqlite:///{DB_PATH}", echo=False)

#基类
class Base(DeclarativeBase):
    pass

#model类
class Employee(Base):
    __tablename__="employees"
    
    id:Mapped[str]=mapped_column(String(50),primary_key=True)
    name:Mapped[str]=mapped_column(String(50))
    department:Mapped[str]=mapped_column(String(50))
    position:Mapped[str]=mapped_column(String(50))

#建表
def create_table():
    Base.metadata.create_all(engine)#自动根据Model建所有表
    
#——4.种子数据

def seed_data():
    from sqlalchemy import select
    with Session(engine) as session:
        #检查是否已有数据
        if session.query(Employee).count()>0:
            print("种子数据已经存在跳过")
            return
        employees = [
         Employee(id="emp_0001", name="张总", department="管理部",
  position="总经理"),
        Employee(id="emp_0002", name="李经理", department="技术部",
  position="部门总监"),
        Employee(id="emp_0003", name="王小明", department="技术部",
  position="工程师"),
  ]
        session.add_all(employees)
        session.commit()   #结账
        
def get_session():
    return Session(engine)


if __name__ == "__main__":
    create_table()
    seed_data()
    # 验证
    with Session(engine) as session:
        for emp in session.query(Employee).all():
            print(f"  {emp.id} | {emp.name} | {emp.department} | {emp.position}")