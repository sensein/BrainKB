# -*- coding: utf-8 -*-
# -----------------------------------------------------------------------------
# DISCLAIMER: This software is provided "as is" without any warranty,
# express or implied, including but not limited to the warranties of
# merchantability, fitness for a particular purpose, and non-infringement.
#
# In no event shall the authors or copyright holders be liable for any
# claim, damages, or other liability, whether in an action of contract,
# tort, or otherwise, arising from, out of, or in connection with the
# software or the use or other dealings in the software.
# -----------------------------------------------------------------------------

from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime, 
    ForeignKey, UniqueConstraint, Index, JSON
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.dialects.postgresql import INET, JSONB

Base = declarative_base()


class User(Base):
    """User authentication table"""
    __tablename__ = "Web_jwtuser"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships - JWT only, no profile relationships
    
    # Indexes
    __table_args__ = (
        Index('idx_user_email', 'email'),
        Index('idx_user_active', 'is_active'),
    )


class Scope(Base):
    """Permission scopes table"""
    __tablename__ = "Web_scope"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user_scopes = relationship("UserScope", back_populates="scope")


class UserScope(Base):
    """User-scope relationship table"""
    __tablename__ = "Web_jwtuser_scopes"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jwtuser_id: Mapped[int] = mapped_column(Integer, ForeignKey("Web_jwtuser.id", ondelete="CASCADE"), nullable=False)
    scope_id: Mapped[int] = mapped_column(Integer, ForeignKey("Web_scope.id", ondelete="CASCADE"), nullable=False)
    
    # Relationships
    user = relationship("User", backref="user_scopes")
    scope = relationship("Scope", back_populates="user_scopes")
    
    # Constraints
    __table_args__ = (
        UniqueConstraint('jwtuser_id', 'scope_id', name='uq_user_scope'),
        Index('idx_user_scope_user', 'jwtuser_id'),
        Index('idx_user_scope_scope', 'scope_id'),
    )


class UserProfile(Base):
    """User profile information table - Independent from JWT, for social login"""
    __tablename__ = "Web_user_profile"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(100), default="Curator", nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    organization: Mapped[Optional[str]] = mapped_column(String(255))
    orcid_id: Mapped[Optional[str]] = mapped_column(String(50))
    github: Mapped[Optional[str]] = mapped_column(String(100))
    linkedin: Mapped[Optional[str]] = mapped_column(String(500))
    google_scholar: Mapped[Optional[str]] = mapped_column(String(100))
    website: Mapped[Optional[str]] = mapped_column(String(500))
    area_of_expertise: Mapped[Optional[str]] = mapped_column(Text)
    country: Mapped[Optional[str]] = mapped_column(String(100))
    conflict_of_interest_statement: Mapped[Optional[str]] = mapped_column(Text)
    biography: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships - other tables link to this profile
    activities = relationship("UserActivity", back_populates="profile", cascade="all, delete-orphan")
    contributions = relationship("UserContribution", back_populates="profile", cascade="all, delete-orphan")
    roles = relationship("UserRole", foreign_keys="[UserRole.profile_id]", cascade="all, delete-orphan")
    
    # Constraints and Indexes
    __table_args__ = (
        UniqueConstraint('email', name='uq_user_profile_email'),
        UniqueConstraint('orcid_id', name='uq_user_profile_orcid_id'),
        Index('idx_user_profile_email', 'email'),
        Index('idx_user_profile_orcid_id', 'orcid_id'),
        Index('idx_user_profile_role', 'role'),
    )


class UserActivity(Base):
    """User activity tracking table - Links to UserProfile, not JWT"""
    __tablename__ = "Web_user_activity"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("Web_user_profile.id", ondelete="CASCADE"), nullable=False)
    activity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    meta_data: Mapped[Optional[dict]] = mapped_column(JSONB)
    ip_address: Mapped[Optional[str]] = mapped_column(INET)
    user_agent: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    profile = relationship("UserProfile", back_populates="activities")
    
    # Indexes
    __table_args__ = (
        Index('idx_user_activity_profile_id', 'profile_id'),
        Index('idx_user_activity_created_at', 'created_at', postgresql_ops={'created_at': 'DESC'}),
        Index('idx_user_activity_type', 'activity_type'),
        Index('idx_user_activity_profile_type', 'profile_id', 'activity_type'),
    )


class UserContribution(Base):
    """User contribution tracking table - Links to UserProfile, not JWT"""
    __tablename__ = "Web_user_contribution"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("Web_user_profile.id", ondelete="CASCADE"), nullable=False)
    contribution_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    content_id: Mapped[Optional[str]] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    meta_data: Mapped[Optional[dict]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    profile = relationship("UserProfile", back_populates="contributions")
    
    # Indexes
    __table_args__ = (
        Index('idx_user_contribution_profile_id', 'profile_id'),
        Index('idx_user_contribution_type', 'contribution_type'),
        Index('idx_user_contribution_status', 'status'),
        Index('idx_user_contribution_created_at', 'created_at', postgresql_ops={'created_at': 'DESC'}),
        Index('idx_user_contribution_profile_type', 'profile_id', 'contribution_type'),
        Index('idx_user_contribution_profile_status', 'profile_id', 'status'),
    )


class UserRole(Base):
    """User role assignment table - Links to UserProfile, not JWT"""
    __tablename__ = "Web_user_role"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("Web_user_profile.id", ondelete="CASCADE"), nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    assigned_by: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("Web_user_profile.id", ondelete="SET NULL"))
    assigned_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships - explicitly specify foreign keys to avoid ambiguity
    profile = relationship("UserProfile", foreign_keys=[profile_id], back_populates="roles")
    assigned_by_profile = relationship("UserProfile", foreign_keys=[assigned_by], post_update=True)
    
    # Constraints and Indexes
    __table_args__ = (
        UniqueConstraint('profile_id', 'role', name='uq_profile_role'),
        Index('idx_user_role_profile_id', 'profile_id'),
        Index('idx_user_role_active', 'is_active'),
        Index('idx_user_role_role', 'role'),
        Index('idx_user_role_profile_active', 'profile_id', 'is_active'),
    ) 