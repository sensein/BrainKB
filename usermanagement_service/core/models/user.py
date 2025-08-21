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
from pydantic import BaseModel, EmailStr, Field, validator


class UserRoleEnum(str, Enum):
    """This is the user role for the BrainKB platform. Each user who are registered will have one of these
    roles, with default being the curator"""
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
    """Different types of user activities."""
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


class ContributionStatus(str, Enum):
    """Contribution status types, contribution statuses"""
    SUBMITTED = "submitted"
    PENDING = "pending"
    REVIEWING = "reviewing"
    APPROVED = "approved"
    REJECTED = "rejected"
    PUBLISHED = "published"
    ARCHIVED = "archived"


# Authentication Models
class UserIn(BaseModel):
    """JWT User registration input model"""
    full_name: str = Field(..., min_length=1, max_length=255, description="User's full name")
    email: EmailStr = Field(..., description="User's email address")
    password: str = Field(..., min_length=8, description="User's password")


class LoginUserIn(BaseModel):
    """JWT User login input model"""
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
class UserCountryInput(BaseModel):
    """User country input model (for creating/updating)"""
    country: str = Field(..., max_length=100, description="Country name")
    is_primary: bool = Field(default=False, description="Whether this is the primary country")
    
    @validator('country')
    def validate_country(cls, v):
        """Validate that the country is one of the allowed values"""
        valid_countries = [
            'United States', 'Canada', 'Mexico', 'United Kingdom', 'Germany', 'France', 
            'Italy', 'Spain', 'Netherlands', 'Switzerland', 'Sweden', 'Norway', 'Denmark', 
            'Finland', 'Belgium', 'Austria', 'Poland', 'Czech Republic', 'Hungary', 
            'Portugal', 'Greece', 'Ireland', 'China', 'Japan', 'South Korea', 'India', 
            'Singapore', 'Taiwan', 'Hong Kong', 'Thailand', 'Malaysia', 'Indonesia', 
            'Philippines', 'Vietnam', 'Pakistan', 'Bangladesh', 'Sri Lanka', 'Nepal', 
            'Myanmar', 'Cambodia', 'Laos', 'Mongolia', 'Kazakhstan', 'Uzbekistan', 
            'Kyrgyzstan', 'Tajikistan', 'Turkmenistan', 'Afghanistan', 'Iran', 'Iraq', 
            'Syria', 'Lebanon', 'Jordan', 'Israel', 'Palestine', 'Saudi Arabia', 'Yemen', 
            'Oman', 'United Arab Emirates', 'Qatar', 'Kuwait', 'Bahrain', 'Australia', 
            'New Zealand', 'Fiji', 'Papua New Guinea', 'Solomon Islands', 'Vanuatu', 
            'New Caledonia', 'French Polynesia', 'Brazil', 'Argentina', 'Chile', 
            'Colombia', 'Peru', 'Venezuela', 'Ecuador', 'Bolivia', 'Paraguay', 'Uruguay', 
            'Guyana', 'Suriname', 'French Guiana', 'South Africa', 'Egypt', 'Nigeria', 
            'Kenya', 'Ethiopia', 'Ghana', 'Morocco', 'Tunisia', 'Algeria', 'Libya', 
            'Sudan', 'South Sudan', 'Chad', 'Niger', 'Mali', 'Burkina Faso', 'Senegal', 
            'Guinea', 'Sierra Leone', 'Liberia', 'Ivory Coast', 'Togo', 'Benin', 
            'Cameroon', 'Central African Republic', 'Gabon', 'Republic of the Congo', 
            'Democratic Republic of the Congo', 'Angola', 'Zambia', 'Zimbabwe', 'Botswana', 
            'Namibia', 'Lesotho', 'Eswatini', 'Madagascar', 'Mauritius', 'Seychelles', 
            'Comoros', 'Mauritania', 'Western Sahara', 'Cape Verde', 'Guinea-Bissau', 
            'Equatorial Guinea', 'São Tomé and Príncipe', 'Djibouti', 'Eritrea', 'Somalia', 
            'Tanzania', 'Uganda', 'Rwanda', 'Burundi', 'Malawi', 'Mozambique'
        ]
        if v not in valid_countries:
            raise ValueError(f'Country must be one of the valid countries. Please check the available countries endpoint.')
        return v


class UserOrganizationInput(BaseModel):
    """User organization input model (for creating/updating)"""
    organization: str = Field(..., max_length=255, description="Organization name")
    position: Optional[str] = Field(None, max_length=255, description="Position/Title at organization")
    department: Optional[str] = Field(None, max_length=255, description="Department within organization")
    is_primary: bool = Field(default=False, description="Whether this is the primary organization")
    start_date: Optional[datetime] = Field(None, description="Start date at organization")
    end_date: Optional[datetime] = Field(None, description="End date at organization (null for current)")


class UserEducationInput(BaseModel):
    """User education input model (for creating/updating)"""
    degree: str = Field(..., max_length=100, description="Degree type (PhD, MSc, BSc, etc.)")
    field_of_study: str = Field(..., max_length=255, description="Field of study (Computer Science, Neuroscience, etc.)")
    institution: str = Field(..., max_length=255, description="Institution name")
    graduation_year: Optional[int] = Field(None, ge=1900, le=2100, description="Graduation year")
    is_primary: bool = Field(default=False, description="Whether this is the primary education")


class UserCountry(BaseModel):
    """User country model (for responses)"""
    id: Optional[int] = None
    profile_id: Optional[int] = None
    country: str = Field(..., max_length=100, description="Country name")
    is_primary: bool = Field(default=False, description="Whether this is the primary country")
    created_at: Optional[datetime] = None


class UserOrganization(BaseModel):
    """User organization model (for responses)"""
    id: Optional[int] = None
    profile_id: Optional[int] = None
    organization: str = Field(..., max_length=255, description="Organization name")
    position: Optional[str] = Field(None, max_length=255, description="Position/Title at organization")
    department: Optional[str] = Field(None, max_length=255, description="Department within organization")
    is_primary: bool = Field(default=False, description="Whether this is the primary organization")
    start_date: Optional[datetime] = Field(None, description="Start date at organization")
    end_date: Optional[datetime] = Field(None, description="End date at organization (null for current)")
    created_at: Optional[datetime] = None


class UserEducation(BaseModel):
    """User education model (for responses)"""
    id: Optional[int] = None
    profile_id: Optional[int] = None
    degree: str = Field(..., max_length=100, description="Degree type (PhD, MSc, BSc, etc.)")
    field_of_study: str = Field(..., max_length=255, description="Field of study (Computer Science, Neuroscience, etc.)")
    institution: str = Field(..., max_length=255, description="Institution name")
    graduation_year: Optional[int] = Field(None, ge=1900, le=2100, description="Graduation year")
    is_primary: bool = Field(default=False, description="Whether this is the primary education")
    created_at: Optional[datetime] = None


class UserExpertiseInput(BaseModel):
    """User expertise input model (for creating/updating)"""
    expertise_area: str = Field(..., max_length=255, description="Area of expertise")
    level: Optional[str] = Field(None, max_length=50, description="Expertise level (Beginner, Intermediate, Expert)")
    years_experience: Optional[int] = Field(None, ge=0, description="Years of experience in this area")


class UserRoleInput(BaseModel):
    """User role input model (for creating/updating)"""
    role: str = Field(..., description="Role name")
    is_active: bool = Field(default=True, description="Whether the role is active")
    expires_at: Optional[datetime] = Field(None, description="Role expiration date")
    
    @validator('role')
    def validate_role(cls, v):
        """Validate that the role is one of the allowed values"""
        valid_roles = [role.value for role in UserRoleEnum]
        if v not in valid_roles:
            raise ValueError(f'Role must be one of: {", ".join(valid_roles)}')
        return v


class UserExpertise(BaseModel):
    """User expertise model (for responses)"""
    id: Optional[int] = None
    profile_id: Optional[int] = None
    expertise_area: str = Field(..., max_length=255, description="Area of expertise")
    level: Optional[str] = Field(None, max_length=50, description="Expertise level (Beginner, Intermediate, Expert)")
    years_experience: Optional[int] = Field(None, ge=0, description="Years of experience in this area")
    created_at: Optional[datetime] = None


class UserProfileInput(BaseModel):
    """User profile input model (for creating/updating)"""
    name: str = Field(..., min_length=1, max_length=255, description="User's display name")
    name_prefix: Optional[str] = Field(None, max_length=50, description="Name prefix (Dr., Prof., etc.)")
    name_suffix: Optional[str] = Field(None, max_length=50, description="Name suffix (Jr., Sr., III, etc.)")
    email: EmailStr = Field(..., description="User's email address")
    orcid_id: Optional[str] = Field(None, max_length=50, description="User's ORCID ID")
    github: Optional[str] = Field(None, max_length=100, description="User's GitHub username")
    linkedin: Optional[str] = Field(None, max_length=500, description="User's LinkedIn profile URL")
    google_scholar: Optional[str] = Field(None, max_length=100, description="User's Google Scholar ID")
    website: Optional[str] = Field(None, max_length=500, description="User's personal website")
    conflict_of_interest_statement: Optional[str] = Field(None, description="User's conflict of interest statement")
    biography: Optional[str] = Field(None, description="User's biography")
    # Many-to-many relationships
    countries: Optional[List[UserCountryInput]] = Field(default_factory=list, description="User's associated countries")
    organizations: Optional[List[UserOrganizationInput]] = Field(default_factory=list, description="User's organizations/affiliations")
    education: Optional[List[UserEducationInput]] = Field(default_factory=list, description="User's education history")
    expertise_areas: Optional[List[UserExpertiseInput]] = Field(default_factory=list, description="User's areas of expertise")
    roles: List[UserRoleInput] = Field(default_factory=lambda: [UserRoleInput(role="Curator")], description="User's roles (defaults to Curator)")


# User Role Models (moved before UserProfile)
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


class UserRoleAssignment(BaseModel):
    """User role assignment model"""
    user_id: int = Field(..., description="User ID to assign role to")
    role: str = Field(..., description="Role to assign")


class UserProfile(BaseModel):
    """User profile model (for responses)"""
    id: Optional[int] = None
    name: str = Field(..., min_length=1, max_length=255, description="User's display name")
    name_prefix: Optional[str] = Field(None, max_length=50, description="Name prefix (Dr., Prof., etc.)")
    name_suffix: Optional[str] = Field(None, max_length=50, description="Name suffix (Jr., Sr., III, etc.)")
    email: EmailStr = Field(..., description="User's email address")
    orcid_id: Optional[str] = Field(None, max_length=50, description="User's ORCID ID")
    github: Optional[str] = Field(None, max_length=100, description="User's GitHub username")
    linkedin: Optional[str] = Field(None, max_length=500, description="User's LinkedIn profile URL")
    google_scholar: Optional[str] = Field(None, max_length=100, description="User's Google Scholar ID")
    website: Optional[str] = Field(None, max_length=500, description="User's personal website")
    conflict_of_interest_statement: Optional[str] = Field(None, description="User's conflict of interest statement")
    biography: Optional[str] = Field(None, description="User's biography")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Many-to-many relationships
    countries: Optional[List[UserCountry]] = Field(default_factory=list, description="User's associated countries")
    organizations: Optional[List[UserOrganization]] = Field(default_factory=list, description="User's organizations/affiliations")
    education: Optional[List[UserEducation]] = Field(default_factory=list, description="User's education history")
    expertise_areas: Optional[List[UserExpertise]] = Field(default_factory=list, description="User's areas of expertise")
    roles: Optional[List[UserRole]] = Field(default_factory=list, description="User's roles")


class ProfileUpdateRequest(BaseModel):
    """User profile update request model"""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    name_prefix: Optional[str] = Field(None, max_length=50)
    name_suffix: Optional[str] = Field(None, max_length=50)
    email: Optional[EmailStr] = Field(None)
    orcid_id: Optional[str] = Field(None, max_length=50)
    github: Optional[str] = Field(None, max_length=100)
    linkedin: Optional[str] = Field(None, max_length=500)
    google_scholar: Optional[str] = Field(None, max_length=100)
    website: Optional[str] = Field(None, max_length=500)
    conflict_of_interest_statement: Optional[str] = Field(None)
    biography: Optional[str] = Field(None)
    # Many-to-many relationships
    countries: Optional[List[UserCountryInput]] = Field(None, description="User's associated countries")
    organizations: Optional[List[UserOrganizationInput]] = Field(None, description="User's associated organizations")
    education: Optional[List[UserEducationInput]] = Field(None, description="User's education history")
    expertise_areas: Optional[List[UserExpertiseInput]] = Field(None, description="User's areas of expertise")
    roles: Optional[List[UserRoleInput]] = Field(None, description="User's assigned roles")


# User Activity Models
class UserActivityInput(BaseModel):
    """User activity input model (for creating)"""
    activity_type: ActivityType = Field(..., description="Type of activity")
    description: Optional[str] = Field(None, description="Activity description")
    meta_data: Optional[Dict[str, Any]] = Field(None, description="Additional activity metadata")
    ip_address: Optional[str] = Field(None, description="User's IP address")
    user_agent: Optional[str] = Field(None, description="User's browser/client information")


class UserActivity(BaseModel):
    """User activity model (for responses)"""
    id: Optional[int] = None
    user_id: Optional[int] = None
    activity_type: ActivityType = Field(..., description="Type of activity")
    description: Optional[str] = Field(None, description="Activity description")
    meta_data: Optional[Dict[str, Any]] = Field(None, description="Additional activity metadata")
    ip_address: Optional[str] = Field(None, description="User's IP address")
    user_agent: Optional[str] = Field(None, description="User's browser/client information")
    created_at: Optional[datetime] = None


# User Contribution Models
class UserContributionInput(BaseModel):
    """User contribution input model (for creating/updating)"""
    contribution_type: ContributionType = Field(..., description="Type of contribution")
    title: str = Field(..., min_length=1, max_length=500, description="Contribution title")
    description: Optional[str] = Field(None, description="Contribution description")
    content_id: Optional[str] = Field(None, max_length=255, description="External content ID")
    status: ContributionStatus = Field(default=ContributionStatus.PENDING, description="Contribution status")
    meta_data: Optional[Dict[str, Any]] = Field(None, description="Additional contribution metadata")


class UserContribution(BaseModel):
    """User contribution model (for responses)"""
    id: Optional[int] = None
    user_id: Optional[int] = None
    contribution_type: ContributionType = Field(..., description="Type of contribution")
    title: str = Field(..., min_length=1, max_length=500, description="Contribution title")
    description: Optional[str] = Field(None, description="Contribution description")
    content_id: Optional[str] = Field(None, max_length=255, description="External content ID")
    status: ContributionStatus = Field(default=ContributionStatus.PENDING, description="Contribution status")
    meta_data: Optional[Dict[str, Any]] = Field(None, description="Additional contribution metadata")
    created_at: Optional[datetime] = None
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


# Management Models
class AvailableRole(BaseModel):
    """Available role model for management"""
    id: Optional[int] = None
    name: str = Field(..., max_length=100, description="Role name")
    description: Optional[str] = Field(None, description="Role description")
    category: Optional[str] = Field(None, max_length=50, description="Role category")
    is_active: bool = Field(default=True, description="Whether the role is active")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AvailableRoleInput(BaseModel):
    """Available role input model for creating/updating"""
    name: str = Field(..., max_length=100, description="Role name")
    description: Optional[str] = Field(None, description="Role description")
    category: Optional[str] = Field(None, max_length=50, description="Role category")
    is_active: bool = Field(default=True, description="Whether the role is active")
    
    @validator('name')
    def validate_role_name(cls, v):
        """Validate that the role name is one of the allowed values"""
        valid_roles = [role.value for role in UserRoleEnum]
        if v not in valid_roles:
            raise ValueError(f'Role name must be one of: {", ".join(valid_roles)}')
        return v
    
    @validator('category')
    def validate_category(cls, v):
        """Validate that the category is one of the allowed values"""
        if v is not None:
            valid_categories = ['Content', 'Quality', 'Knowledge', 'Community']
            if v not in valid_categories:
                raise ValueError(f'Category must be one of: {", ".join(valid_categories)}')
        return v


class AvailableCountry(BaseModel):
    """Available country model for management"""
    id: Optional[int] = None
    name: str = Field(..., max_length=100, description="Country name")
    code: Optional[str] = Field(None, max_length=3, description="ISO 3166-1 alpha-3 code")
    code_2: Optional[str] = Field(None, max_length=2, description="ISO 3166-1 alpha-2 code")
    region: Optional[str] = Field(None, max_length=50, description="Continent/Region")
    is_active: bool = Field(default=True, description="Whether the country is active")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class AvailableCountryInput(BaseModel):
    """Available country input model for creating/updating"""
    name: str = Field(..., max_length=100, description="Country name")
    code: Optional[str] = Field(None, max_length=3, description="ISO 3166-1 alpha-3 code")
    code_2: Optional[str] = Field(None, max_length=2, description="ISO 3166-1 alpha-2 code")
    region: Optional[str] = Field(None, max_length=50, description="Continent/Region")
    is_active: bool = Field(default=True, description="Whether the country is active")
    
    @validator('region')
    def validate_region(cls, v):
        """Validate that the region is one of the allowed values"""
        if v is not None:
            valid_regions = ['North America', 'Europe', 'Asia', 'Oceania', 'South America', 'Africa']
            if v not in valid_regions:
                raise ValueError(f'Region must be one of: {", ".join(valid_regions)}')
        return v
