from django.contrib import admin
from .models import JWTUser, Scope
# Register your models here.

class JWTUserAdmin(admin.ModelAdmin):
    list_display = ( 'email', 'full_name', 'is_active',"created_at", "updated_at")
    list_filter = ( 'email', "is_active")

class ScopeAdmin(admin.ModelAdmin):
    list_display = ('name', 'description', 'created_at')

admin.site.register(Scope, ScopeAdmin)
admin.site.register(JWTUser, JWTUserAdmin)