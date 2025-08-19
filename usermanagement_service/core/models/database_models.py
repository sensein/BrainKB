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


class JWTUser(Base):
    """JWT User authentication table"""
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
        Index('idx_jwtuser_email', 'email'),
        Index('idx_jwtuser_active', 'is_active'),
    )


class JWTScope(Base):
    """JWT Permission scopes table"""
    __tablename__ = "Web_scope"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    jwt_user_scopes = relationship("JWTUserScope", back_populates="scope")


class JWTUserScope(Base):
    """JWT User-scope relationship table"""
    __tablename__ = "Web_jwtuser_scopes"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    jwtuser_id: Mapped[int] = mapped_column(Integer, ForeignKey("Web_jwtuser.id", ondelete="CASCADE"), nullable=False)
    scope_id: Mapped[int] = mapped_column(Integer, ForeignKey("Web_scope.id", ondelete="CASCADE"), nullable=False)
    
    # Relationships
    jwt_user = relationship("JWTUser", backref="jwt_user_scopes")
    scope = relationship("JWTScope", back_populates="jwt_user_scopes")
    
    # Constraints
    __table_args__ = (
        UniqueConstraint('jwtuser_id', 'scope_id', name='uq_jwtuser_scope'),
        Index('idx_jwtuser_scope_user', 'jwtuser_id'),
        Index('idx_jwtuser_scope_scope', 'scope_id'),
    )


class UserProfile(Base):
    """User profile information table - Independent from JWT, for social login"""
    __tablename__ = "Web_user_profile"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_prefix: Mapped[Optional[str]] = mapped_column(String(50))
    name_suffix: Mapped[Optional[str]] = mapped_column(String(50))
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    orcid_id: Mapped[Optional[str]] = mapped_column(String(50))
    github: Mapped[Optional[str]] = mapped_column(String(100))
    linkedin: Mapped[Optional[str]] = mapped_column(String(500))
    google_scholar: Mapped[Optional[str]] = mapped_column(String(100))
    website: Mapped[Optional[str]] = mapped_column(String(500))
    conflict_of_interest_statement: Mapped[Optional[str]] = mapped_column(Text)
    biography: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships - other tables link to this profile
    activities = relationship("UserActivity", back_populates="profile", cascade="all, delete-orphan")
    contributions = relationship("UserContribution", back_populates="profile", cascade="all, delete-orphan")
    roles = relationship("UserRole", foreign_keys="[UserRole.profile_id]", cascade="all, delete-orphan")
    countries = relationship("UserCountry", back_populates="profile", cascade="all, delete-orphan")
    organizations = relationship("UserOrganization", back_populates="profile", cascade="all, delete-orphan")
    education = relationship("UserEducation", back_populates="profile", cascade="all, delete-orphan")
    expertise_areas = relationship("UserExpertise", back_populates="profile", cascade="all, delete-orphan")
    
    # Constraints and Indexes
    __table_args__ = (
        UniqueConstraint('email', name='uq_user_profile_email'),
        UniqueConstraint('orcid_id', name='uq_user_profile_orcid_id'),
        Index('idx_user_profile_email', 'email'),
        Index('idx_user_profile_orcid_id', 'orcid_id'),
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


class UserCountry(Base):
    """User country association table - Many-to-many relationship"""
    __tablename__ = "Web_user_country"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("Web_user_profile.id", ondelete="CASCADE"), nullable=False)
    country: Mapped[str] = mapped_column(String(100), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    profile = relationship("UserProfile", back_populates="countries")
    
    # Constraints and Indexes
    __table_args__ = (
        UniqueConstraint('profile_id', 'country', name='uq_profile_country'),
        Index('idx_user_country_profile_id', 'profile_id'),
        Index('idx_user_country_country', 'country'),
        Index('idx_user_country_primary', 'is_primary'),
    )


class UserExpertise(Base):
    """User expertise area table - Many-to-many relationship"""
    __tablename__ = "Web_user_expertise"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("Web_user_profile.id", ondelete="CASCADE"), nullable=False)
    expertise_area: Mapped[str] = mapped_column(String(255), nullable=False)
    level: Mapped[Optional[str]] = mapped_column(String(50))  # e.g., "Beginner", "Intermediate", "Expert"
    years_experience: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    profile = relationship("UserProfile", back_populates="expertise_areas")
    
    # Constraints and Indexes
    __table_args__ = (
        UniqueConstraint('profile_id', 'expertise_area', name='uq_profile_expertise'),
        Index('idx_user_expertise_profile_id', 'profile_id'),
        Index('idx_user_expertise_area', 'expertise_area'),
        Index('idx_user_expertise_level', 'level'),
    )


class UserOrganization(Base):
    """User organization association table - Many-to-many relationship"""
    __tablename__ = "Web_user_organization"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("Web_user_profile.id", ondelete="CASCADE"), nullable=False)
    organization: Mapped[str] = mapped_column(String(255), nullable=False)
    position: Mapped[Optional[str]] = mapped_column(String(255))
    department: Mapped[Optional[str]] = mapped_column(String(255))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    profile = relationship("UserProfile", back_populates="organizations")
    
    # Constraints and Indexes
    __table_args__ = (
        UniqueConstraint('profile_id', 'organization', name='uq_profile_organization'),
        Index('idx_user_organization_profile_id', 'profile_id'),
        Index('idx_user_organization_name', 'organization'),
        Index('idx_user_organization_primary', 'is_primary'),
    )


class UserEducation(Base):
    """User education history table - Many-to-many relationship"""
    __tablename__ = "Web_user_education"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(Integer, ForeignKey("Web_user_profile.id", ondelete="CASCADE"), nullable=False)
    degree: Mapped[str] = mapped_column(String(100), nullable=False)
    field_of_study: Mapped[str] = mapped_column(String(255), nullable=False)
    institution: Mapped[str] = mapped_column(String(255), nullable=False)
    graduation_year: Mapped[Optional[int]] = mapped_column(Integer)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    profile = relationship("UserProfile", back_populates="education")
    
    # Constraints and Indexes
    __table_args__ = (
        UniqueConstraint('profile_id', 'degree', 'institution', name='uq_profile_education'),
        Index('idx_user_education_profile_id', 'profile_id'),
        Index('idx_user_education_degree', 'degree'),
        Index('idx_user_education_institution', 'institution'),
        Index('idx_user_education_primary', 'is_primary'),
    )


class AvailableRole(Base):
    """Available roles for the platform - Management table"""
    __tablename__ = "Web_available_role"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(String(50))  # Content, Quality, Knowledge, Community
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Constraints and Indexes
    __table_args__ = (
        Index('idx_available_role_name', 'name'),
        Index('idx_available_role_category', 'category'),
        Index('idx_available_role_active', 'is_active'),
    )


class AvailableCountry(Base):
    """Available countries for user profiles - Management table"""
    __tablename__ = "Web_available_country"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    code: Mapped[Optional[str]] = mapped_column(String(3))  # ISO 3166-1 alpha-3
    code_2: Mapped[Optional[str]] = mapped_column(String(2))  # ISO 3166-1 alpha-2
    region: Mapped[Optional[str]] = mapped_column(String(50))  # Continent/Region
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Constraints and Indexes
    __table_args__ = (
        Index('idx_available_country_name', 'name'),
        Index('idx_available_country_code', 'code'),
        Index('idx_available_country_code_2', 'code_2'),
        Index('idx_available_country_region', 'region'),
        Index('idx_available_country_active', 'is_active'),
    )