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
from typing import Optional, List, Dict, Any
from enum import Enum
from pydantic import BaseModel, EmailStr, Field


class UserRole(str, Enum):
    """User roles for the BrainKB platform"""
    # Content Contribution Roles
    SUBMITTER = "Submitter"
    ANNOTATOR = "Annotator"
    MAPPER = "Mapper"
    CURATOR = "Curator"
    
    # Quality Control Roles
    REVIEWER = "Reviewer"
    VALIDATOR = "Validator"
    CONFLICT_RESOLVER = "Conflict Resolver"
    
    # Knowledge Management Roles
    KNOWLEDGE_CONTRIBUTOR = "Knowledge Contributor"
    EVIDENCE_TRACER = "Evidence Tracer"
    PROVENANCE_TRACKER = "Provenance Tracker"
    
    # Community Management Roles
    MODERATOR = "Moderator"
    AMBASSADOR = "Ambassador"


class ActivityType(str, Enum):
    """Types of user activities"""
    LOGIN = "login"
    LOGOUT = "logout"
    REGISTER = "register"
    PROFILE_UPDATE = "profile_update"
    CONTENT_SUBMISSION = "content_submission"
    CONTENT_ANNOTATION = "content_annotation"
    CONTENT_REVIEW = "content_review"
    CONTENT_VALIDATION = "content_validation"
    CONTENT_MAPPING = "content_mapping"
    CONTENT_CURATION = "content_curation"
    EVIDENCE_LINKING = "evidence_linking"
    PROVENANCE_TRACKING = "provenance_tracking"
    CONFLICT_RESOLUTION = "conflict_resolution"
    DISCUSSION_PARTICIPATION = "discussion_participation"
    COMMUNITY_OUTREACH = "community_outreach"


class ContributionType(str, Enum):
    """Types of user contributions"""
    PAPER = "paper"
    DATASET = "dataset"
    MODEL = "model"
    ANNOTATION = "annotation"
    MAPPING = "mapping"
    REVIEW = "review"
    VALIDATION = "validation"
    EVIDENCE = "evidence"
    PROVENANCE = "provenance"
    DISCUSSION = "discussion"
    OUTREACH = "outreach"


# Authentication Models
class UserIn(BaseModel):
    """User registration input model"""
    full_name: str = Field(..., min_length=1, max_length=255, description="User's full name")
    email: EmailStr = Field(..., description="User's email address")
    password: str = Field(..., min_length=8, description="User's password")


class LoginUserIn(BaseModel):
    """User login input model"""
    email: EmailStr = Field(..., description="User's email address")
    password: str = Field(..., description="User's password")


class JWTUser(BaseModel):
    """JWT user model"""
    id: int
    full_name: str
    email: EmailStr
    is_active: bool
    created_at: datetime
    updated_at: datetime


# User Profile Models
class UserProfile(BaseModel):
    """User profile model"""
    id: Optional[int] = None
    user_id: Optional[int] = None
    name: str = Field(..., min_length=1, max_length=255, description="User's display name")
    role: str = Field(default="Curator", description="User's primary role")
    email: EmailStr = Field(..., description="User's email address")
    organization: Optional[str] = Field(None, max_length=255, description="User's organization")
    orcid_id: Optional[str] = Field(None, max_length=50, description="User's ORCID ID")
    github: Optional[str] = Field(None, max_length=100, description="User's GitHub username")
    linkedin: Optional[str] = Field(None, max_length=500, description="User's LinkedIn profile URL")
    google_scholar: Optional[str] = Field(None, max_length=100, description="User's Google Scholar ID")
    website: Optional[str] = Field(None, max_length=500, description="User's personal website")
    area_of_expertise: Optional[str] = Field(None, description="User's area of expertise")
    country: Optional[str] = Field(None, max_length=100, description="User's country")
    conflict_of_interest_statement: Optional[str] = Field(None, description="User's conflict of interest statement")
    biography: Optional[str] = Field(None, description="User's biography")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ProfileUpdateRequest(BaseModel):
    """User profile update request model"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    role: Optional[str] = Field(None)
    email: Optional[EmailStr] = Field(None)
    organization: Optional[str] = Field(None, max_length=255)
    orcid_id: Optional[str] = Field(None, max_length=50)
    github: Optional[str] = Field(None, max_length=100)
    linkedin: Optional[str] = Field(None, max_length=500)
    google_scholar: Optional[str] = Field(None, max_length=100)
    website: Optional[str] = Field(None, max_length=500)
    area_of_expertise: Optional[str] = Field(None)
    country: Optional[str] = Field(None, max_length=100)
    conflict_of_interest_statement: Optional[str] = Field(None)
    biography: Optional[str] = Field(None)


# User Activity Models
class UserActivity(BaseModel):
    """User activity model"""
    id: Optional[int] = None
    user_id: Optional[int] = None
    activity_type: ActivityType = Field(..., description="Type of activity")
    description: Optional[str] = Field(None, description="Activity description")
    meta_data: Optional[Dict[str, Any]] = Field(None, description="Additional activity metadata")
    ip_address: Optional[str] = Field(None, description="User's IP address")
    user_agent: Optional[str] = Field(None, description="User's browser/client information")
    created_at: Optional[datetime] = None


# User Contribution Models
class UserContribution(BaseModel):
    """User contribution model"""
    id: Optional[int] = None
    user_id: Optional[int] = None
    contribution_type: ContributionType = Field(..., description="Type of contribution")
    title: str = Field(..., min_length=1, max_length=500, description="Contribution title")
    description: Optional[str] = Field(None, description="Contribution description")
    content_id: Optional[str] = Field(None, max_length=255, description="External content ID")
    status: str = Field(default="pending", description="Contribution status")
    meta_data: Optional[Dict[str, Any]] = Field(None, description="Additional contribution metadata")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# User Role Models
class UserRoleAssignment(BaseModel):
    """User role assignment model"""
    user_id: int = Field(..., description="User ID to assign role to")
    role: UserRole = Field(..., description="Role to assign")


class UserRole(BaseModel):
    """User role model"""
    id: Optional[int] = None
    user_id: Optional[int] = None
    role: str = Field(..., description="Role name")
    assigned_by: Optional[int] = Field(None, description="User ID who assigned the role")
    assigned_at: Optional[datetime] = None
    is_active: bool = Field(default=True, description="Whether the role is active")
    expires_at: Optional[datetime] = Field(None, description="Role expiration date")
    updated_at: Optional[datetime] = None


# User Statistics Models
class UserStats(BaseModel):
    """User statistics model"""
    total_contributions: int = Field(0, description="Total number of contributions")
    contributions_by_type: Dict[str, int] = Field(default_factory=dict, description="Contributions broken down by type")
    total_activities: int = Field(0, description="Total number of activities")
    last_login: Optional[datetime] = Field(None, description="Last login timestamp")
    account_age_days: int = Field(0, description="Account age in days")
    active_roles: List[str] = Field(default_factory=list, description="User's active roles")
