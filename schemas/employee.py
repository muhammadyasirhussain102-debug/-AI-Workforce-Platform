from datetime import date
from typing import Optional
from pydantic import BaseModel, UUID4, EmailStr

# Incoming employee.created event payload
class EmployeeCreatedEvent(BaseModel):
    tenant_id: UUID4
    employee_id: UUID4
    email: EmailStr
    full_name: str
    department: str
    role: str
    join_date: date = date.today()
    is_probation: bool = True

# Employee ka basic context jo session se milega
class EmployeeProfile(BaseModel):
    employee_id: UUID4
    tenant_id: UUID4
    full_name: str
    email: str
    role: str
    department: str
    is_probation: bool