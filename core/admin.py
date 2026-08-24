# ==================== ADMIN.PY ====================
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Usuario

@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ('Informações Adicionais', {'fields': ('tipo', 'setor')}),
    )
    list_display = ['username', 'tipo']
    list_filter = ['tipo']