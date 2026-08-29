from pydantic import BaseModel, EmailStr, Field, model_validator


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)
    remember: bool = False


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=10, max_length=1024)

    @model_validator(mode="after")
    def passwords_must_differ(self):
        if self.current_password == self.new_password:
            raise ValueError("New password must be different from the current password")
        return self


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=32, max_length=512)
    new_password: str = Field(min_length=10, max_length=1024)


class AdminCreateInstructorRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    temporary_password: str = Field(min_length=10, max_length=1024)


class AdminUpdateInstructorRequest(BaseModel):
    is_active: bool


class AdminResetPasswordRequest(BaseModel):
    temporary_password: str = Field(min_length=10, max_length=1024)
