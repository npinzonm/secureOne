"""Errores de autenticación. Mensajes según PD-17 (APROBADO)."""

from app.core.errors import AppError, BusinessRuleError, ForbiddenError, NotAuthenticatedError


class InvalidCredentialsError(NotAuthenticatedError):
    code = "INVALID_CREDENTIALS"
    message = "Usuario o contraseña inválidos."


class AccountLockedError(AppError):
    status_code = 423
    code = "ACCOUNT_LOCKED"
    message = "Cuenta bloqueada temporalmente por intentos fallidos. Intente más tarde."


class SessionEndedError(NotAuthenticatedError):
    code = "SESSION_ENDED"
    message = "Su sesión finalizó. Inicie sesión nuevamente."


class PasswordChangeRequiredError(ForbiddenError):
    code = "PASSWORD_CHANGE_REQUIRED"
    message = "Debe establecer una nueva contraseña para continuar."


class PasswordPolicyError(BusinessRuleError):
    code = "PASSWORD_POLICY"
    message = "La nueva contraseña no cumple la política de contraseñas."


class InvalidCurrentPasswordError(BusinessRuleError):
    code = "INVALID_CURRENT_PASSWORD"
    message = "La contraseña actual no es correcta."
