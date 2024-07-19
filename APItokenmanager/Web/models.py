from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

class Scope(models.Model):
    name = models.CharField(max_length=100, unique=True, default="read")
    description = models.TextField(default="Provides read access to this scope")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class JWTUser(models.Model):
    full_name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=255)
    is_active = models.BooleanField(default=False)
    scopes = models.ManyToManyField(Scope)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super(JWTUser, self).save(*args, **kwargs)
        if is_new:
            default_scope = Scope.objects.get_or_create(name='read', defaults={'description': 'Provides read access to this scope'})[0]
            self.scopes.add(default_scope)

