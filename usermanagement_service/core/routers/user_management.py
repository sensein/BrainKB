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
from typing import List, Optional, Annotated
from fastapi import APIRouter, HTTPException, Depends, Request, Query
import logging

from core.models.user import (
    # import some to be reused later
    UserProfile, UserProfileInput, ProfileUpdateRequest, UserActivity, UserContribution, UserContributionInput,
    UserRoleAssignment, UserStats, UserRole, UserRoleInput, ActivityType, ContributionType, ContributionStatus,
    UserCountry, UserCountryInput, UserOrganization, UserOrganizationInput, UserEducation, UserEducationInput,
    UserExpertise, UserExpertiseInput, AvailableRole, AvailableRoleInput, AvailableCountry, AvailableCountryInput
)
from core.database import (
    user_db_manager, jwt_user_repo, user_profile_repo, user_activity_repo,
    user_contribution_repo, user_role_repo, user_country_repo, user_organization_repo,
    user_education_repo, user_expertise_repo, available_role_repo, available_country_repo
)
from core.security import get_current_user, require_scopes, require_all_scopes
from core.shared import convert_row_to_dict
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["User Management"])



# User Profile Endpoints
@router.get("/profile", response_model=UserProfile)
async def get_profile(
jwt_user: Annotated[dict, Depends(get_current_user)],
    email: str = Query(..., description="User email"),

    orcid_id: Optional[str] = Query(None, description="User ORCID ID (optional)"),

):
    """This endpoint gets a user profile. Note the user profile here is not the JWT user but a user who makes
    contributes to the BraibKB platform, i.e., the scientists who act in different roles such as curators,
    reviewers and so on. The login is handeled by the UI side via social login.
    We use the email as the primary

    /api/users/profile?email=jani.doea@neuroscience.edu

    Output:
    {
    "id": 5,
    "name": "Jani Doea",
    "name_prefix": "Dr.",
    "name_suffix": "Jr.",
    "email": "jani.doea@neuroscience.edu",
    "orcid_id": "0000-0001-2345-6781",
    "github": "janedoe",
    "linkedin": "https://linkedin.com/in/janedoe",
    "google_scholar": "janedoe_123",
    "website": "https://janedoe.neuroscience.edu",
    "conflict_of_interest_statement": "No conflicts of interest to declare",
    "biography": "Dr. Jani Doea is a leading researcher in cognitive neuroscience...",
    "created_at": "2025-08-19T16:47:04.711814",
    "updated_at": "2025-08-19T16:47:04.711824",
    "countries": [
        {
            "id": 4,
            "profile_id": 5,
            "country": "United States",
            "is_primary": true,
            "created_at": "2025-08-19T16:47:04.982697"
        }
    ],
    "organizations": [
        {
            "id": 2,
            "profile_id": 5,
            "organization": "Stanford University",
            "position": "Associate Professor",
            "department": "Department of Psychology",
            "is_primary": true,
            "start_date": "2020-01-01T00:00:00",
            "end_date": null,
            "created_at": "2025-08-19T16:47:05.234008"
        }
    ],
    "education": [
        {
            "id": 2,
            "profile_id": 5,
            "degree": "PhD",
            "field_of_study": "Neuroscience",
            "institution": "Harvard University",
            "graduation_year": 2015,
            "is_primary": true,
            "created_at": "2025-08-19T16:47:05.481984"
        }
    ],
    "expertise_areas": [
        {
            "id": 4,
            "profile_id": 5,
            "expertise_area": "Cognitive Neuroscience",
            "level": "Expert",
            "years_experience": 15,
            "created_at": "2025-08-19T16:47:05.670266"
        }
    ],
    "roles": [
        {
            "id": 1,
            "user_id": null,
            "role": "Curator",
            "assigned_by": null,
            "assigned_at": "2025-08-19T16:47:05.908865",
            "is_active": true,
            "expires_at": null,
            "updated_at": "2025-08-19T16:47:05.908879"
        }
    ]
}

    """

    try:
        async with user_db_manager.get_async_session() as session:

            profile = await user_profile_repo.get_by_email(session, email)
            if not profile and orcid_id:
                # If no profile found by email, try by ORCID ID
                profile = await user_profile_repo.get_by_orcid_id(session, orcid_id)

            if not profile:
                raise HTTPException(status_code=404, detail="Profile not found")
            
            # Load related data
            countries = await user_country_repo.get_user_countries(session, profile.id)
            organizations = await user_organization_repo.get_user_organizations(session, profile.id)
            education = await user_education_repo.get_user_education(session, profile.id)
            expertise_areas = await user_expertise_repo.get_user_expertise(session, profile.id)
            roles = await user_role_repo.get_user_roles(session, profile.id)
            
            # Convert to Pydantic models
            countries_list = [UserCountry(**convert_row_to_dict(country)) for country in countries]
            organizations_list = [UserOrganization(**convert_row_to_dict(org)) for org in organizations]
            education_list = [UserEducation(**convert_row_to_dict(edu)) for edu in education]
            expertise_list = [UserExpertise(**convert_row_to_dict(expertise)) for expertise in expertise_areas]
            roles_list = [UserRole(**convert_row_to_dict(role)) for role in roles]
            
            # Create complete profile response
            profile_dict = convert_row_to_dict(profile)
            profile_dict['countries'] = countries_list
            profile_dict['organizations'] = organizations_list
            profile_dict['education'] = education_list
            profile_dict['expertise_areas'] = expertise_list
            profile_dict['roles'] = roles_list
            
            return UserProfile(**profile_dict)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting profile for {email}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error")


@router.post("/profile", response_model=dict)
async def create_profile(jwt_user: Annotated[dict, Depends(get_current_user)],
                         profile: UserProfileInput):

    """"This endpoint creates a user profile. Note the user profile here is not the JWT user but a user who makes
    contributes to the BraibKB platform, i.e., the scientists who act in different roles such as curators,
    reviewers and so on. The login is handeled by the UI side via social login.

    The role is curator is default. you can add other roles as

    "roles": [
    {
      "role": "Reviewer",
      "is_active": true
    },
    {
      "role": "Annotator",
      "is_active": true
    }
  ]

    Example input:

    Minimal profile:

    {
  "name": "John Smith",
  "name_prefix": "Dr.",
  "email": "john.smith@example.com",
  "organizations": [
    {
      "organization": "University of Example",
      "position": "Professor",
      "is_primary": true
    }
  ],
  "education": [
    {
      "degree": "PhD",
      "field_of_study": "Computer Science",
      "institution": "MIT",
      "graduation_year": 2010,
      "is_primary": true
    }
  ]
}

        {
  "name": "Jani Doea",
  "name_prefix": "Dr.",
  "name_suffix": "Jr.",
  "email": "jani.doea@neuroscience.edu",
  "orcid_id": "0000-0001-2345-6781",
  "github": "janedoe",
  "linkedin": "https://linkedin.com/in/janedoe",
  "google_scholar": "janedoe_123",
  "website": "https://janedoe.neuroscience.edu",
  "conflict_of_interest_statement": "No conflicts of interest to declare",
  "biography": "Dr. Jani Doea is a leading researcher in cognitive neuroscience...",
  "countries": [
    {
      "country": "United States",
      "is_primary": true
    }
  ],
  "organizations": [
    {
      "organization": "Stanford University",
      "position": "Associate Professor",
      "department": "Department of Psychology",
      "is_primary": true,
      "start_date": "2020-01-01T00:00:00",
      "end_date": null
    }
  ],
  "education": [
    {
      "degree": "PhD",
      "field_of_study": "Neuroscience",
      "institution": "Harvard University",
      "graduation_year": 2015,
      "is_primary": true
    }
  ],
  "expertise_areas": [
    {
      "expertise_area": "Cognitive Neuroscience",
      "level": "Expert",
      "years_experience": 15
    }
  ]

}
    """

    try:
        async with user_db_manager.get_async_session() as session:
            countries_data = profile.countries or []
            organizations_data = profile.organizations or []
            education_data = profile.education or []
            expertise_data = profile.expertise_areas or []
            roles_data = profile.roles or []

            profile_data = profile.dict(exclude={'countries', 'organizations', 'education', 'expertise_areas', 'roles'})
            profile_instance = await user_profile_repo.create_or_update_profile(
                session=session,
                **profile_data
            )

            # Add countries if provided
            for country_data in countries_data:
                await user_country_repo.add_country(
                    session=session,
                    profile_id=profile_instance.id,
                    country=country_data.country,
                    is_primary=country_data.is_primary
                )

            # Add organizations if provided
            for org_data in organizations_data:
                await user_organization_repo.add_organization(
                    session=session,
                    profile_id=profile_instance.id,
                    organization=org_data.organization,
                    position=org_data.position,
                    department=org_data.department,
                    is_primary=org_data.is_primary,
                    start_date=org_data.start_date,
                    end_date=org_data.end_date
                )

            # Add education if provided
            for edu_data in education_data:
                await user_education_repo.add_education(
                    session=session,
                    profile_id=profile_instance.id,
                    degree=edu_data.degree,
                    field_of_study=edu_data.field_of_study,
                    institution=edu_data.institution,
                    graduation_year=edu_data.graduation_year,
                    is_primary=edu_data.is_primary
                )

            # Add expertise areas if provided
            for expertise_data in expertise_data:
                await user_expertise_repo.add_expertise(
                    session=session,
                    profile_id=profile_instance.id,
                    expertise_area=expertise_data.expertise_area,
                    level=expertise_data.level,
                    years_experience=expertise_data.years_experience
                )

            # Add roles if provided
            for role_data in roles_data:
                await user_role_repo.assign_role(
                    session=session,
                    profile_id=profile_instance.id,
                    role=role_data.role,
                    is_active=role_data.is_active,
                    expires_at=role_data.expires_at
                )

            # Log activity
            await user_activity_repo.log_activity(
                session=session,
                profile_id=profile_instance.id,
                activity_type=ActivityType.PROFILE_UPDATE,
                description="Profile created/updated"
            )

            return {"message": "Profile created successfully", "profile_id": profile_instance.id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating profile: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Internal server error {e}")


@router.put("/profile", response_model=dict)
async def update_profile(
jwt_user: Annotated[dict, Depends(get_current_user)],
    profile_update: ProfileUpdateRequest,
    email: str = Query(..., description="User email"),
    orcid_id: Optional[str] = Query(None, description="User ORCID ID (optional)"),

):
    """Update user profile by email or ORCID ID (JWT protected)"""
    try:
        # Remove None values
        update_data = {k: v for k, v in profile_update.dict().items() if v is not None}
        
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        async with user_db_manager.get_async_session() as session:
            # Get profile by email or ORCID
            profile = await user_profile_repo.get_by_email(session, email)
            if not profile and orcid_id:
                profile = await user_profile_repo.get_by_orcid_id(session, orcid_id)
            
            if not profile:
                raise HTTPException(status_code=404, detail="Profile not found")
            
            # Extract countries and expertise_areas before updating profile
            countries_data = update_data.pop('countries', None)
            expertise_data = update_data.pop('expertise_areas', None)
            
            # Update profile with new data
            for key, value in update_data.items():
                if hasattr(profile, key):
                    setattr(profile, key, value)
            profile.updated_at = datetime.utcnow()
            await session.flush()
            await session.refresh(profile)
            
            # Update countries if provided
            if countries_data is not None:
                # Remove existing countries and add new ones
                await user_country_repo.remove_all_countries(session, profile.id)
                for country_data in countries_data:
                    await user_country_repo.add_country(
                        session=session,
                        profile_id=profile.id,
                        country=country_data.country,
                        is_primary=country_data.is_primary
                    )
            
            # Update expertise areas if provided
            if expertise_data is not None:
                # Remove existing expertise areas and add new ones
                await user_expertise_repo.remove_all_expertise(session, profile.id)
                for expertise_data in expertise_data:
                    await user_expertise_repo.add_expertise(
                        session=session,
                        profile_id=profile.id,
                        expertise_area=expertise_data.expertise_area,
                        level=expertise_data.level,
                        years_experience=expertise_data.years_experience
                    )
            
            # Log activity
            await user_activity_repo.log_activity(
                session=session,
                profile_id=profile.id,
                activity_type=ActivityType.PROFILE_UPDATE,
                description="Profile updated"
            )
            
            return {"message": "Profile updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating profile for {email}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")

