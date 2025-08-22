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
):
    """Update user profile by email or ORCID ID (JWT protected)"""
    try:
        # Add basic logging
        logger.info("=== PUT /profile endpoint called ===")
        logger.info(f"Profile update request type: {type(profile_update)}")
        logger.info(f"Raw profile_update: {profile_update}")
        
        # Remove None values
        update_data = {k: v for k, v in profile_update.dict().items() if v is not None}
        
        logger.info(f"Update data after removing None values: {update_data}")
        
        if not update_data:
            raise HTTPException(status_code=400, detail="No fields to update")
        
        async with user_db_manager.get_async_session() as session:
            # Extract email and orcid_id from the request body
            email = update_data.get('email')
            orcid_id = update_data.get('orcid_id')
            
            if not email and not orcid_id:
                raise HTTPException(status_code=400, detail="Either email or orcid_id must be provided in the request body")
            
            # Get profile by email or ORCID
            profile = None
            if email:
                profile = await user_profile_repo.get_by_email(session, email)
            if not profile and orcid_id:
                profile = await user_profile_repo.get_by_orcid_id(session, orcid_id)
            
            if not profile:
                raise HTTPException(status_code=404, detail="Profile not found")
            
            # Extract nested data before updating profile
            countries_data = update_data.pop('countries', None)
            organizations_data = update_data.pop('organizations', None)
            education_data = update_data.pop('education', None)
            expertise_data = update_data.pop('expertise_areas', None)
            roles_data = update_data.pop('roles', None)
            
            # Update profile with new data
            for key, value in update_data.items():
                if hasattr(profile, key):
                    setattr(profile, key, value)
            profile.updated_at = datetime.utcnow()
            await session.flush()
            await session.refresh(profile)
            
            # Update countries if provided
            if countries_data is not None:
                logger.info(f"Updating countries: {countries_data}")
                await user_country_repo.remove_all_countries(session, profile.id)
                for country_data in countries_data:
                    await user_country_repo.add_country(
                        session=session,
                        profile_id=profile.id,
                        country=country_data['country'],
                        is_primary=country_data['is_primary']
                    )
            
            # Update organizations if provided
            if organizations_data is not None:
                logger.info(f"Updating organizations: {organizations_data}")
                await user_organization_repo.remove_all_organizations(session, profile.id)
                for org_data in organizations_data:
                    await user_organization_repo.add_organization(
                        session=session,
                        profile_id=profile.id,
                        organization=org_data['organization'],
                        position=org_data['position'],
                        department=org_data.get('department'),
                        is_primary=org_data['is_primary'],
                        start_date=org_data.get('start_date'),
                        end_date=org_data.get('end_date')
                    )
            
            # Update education if provided
            if education_data is not None:
                logger.info(f"Updating education: {education_data}")
                await user_education_repo.remove_all_education(session, profile.id)
                for edu_data in education_data:
                    await user_education_repo.add_education(
                        session=session,
                        profile_id=profile.id,
                        degree=edu_data['degree'],
                        field_of_study=edu_data['field_of_study'],
                        institution=edu_data['institution'],
                        graduation_year=edu_data['graduation_year'],
                        is_primary=edu_data['is_primary']
                    )
            
            # Update expertise areas if provided
            if expertise_data is not None:
                logger.info(f"Updating expertise areas: {expertise_data}")
                await user_expertise_repo.remove_all_expertise(session, profile.id)
                for exp_data in expertise_data:
                    await user_expertise_repo.add_expertise(
                        session=session,
                        profile_id=profile.id,
                        expertise_area=exp_data['expertise_area'],
                        level=exp_data['level'],
                        years_experience=exp_data['years_experience']
                    )
            
            # Update roles if provided
            if roles_data is not None:
                logger.info(f"Updating roles: {roles_data}")
                await user_role_repo.remove_all_roles(session, profile.id)
                for role_data in roles_data:
                    await user_role_repo.assign_role(
                        session=session,
                        profile_id=profile.id,
                        role=role_data['role'],
                        is_active=role_data['is_active']
                    )
            
            # Log activity
            await user_activity_repo.log_activity(
                session=session,
                profile_id=profile.id,
                activity_type=ActivityType.PROFILE_UPDATE,
                description="Profile updated"
            )
            
            # Commit all changes
            await session.commit()
            logger.info("Profile update completed successfully")
            
            return {"message": "Profile updated successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating profile for {email}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


# User Activity Endpoints
@router.get("/activities", response_model=List[UserActivity])
async def get_activities(
        jwt_user: Annotated[dict, Depends(get_current_user)],
        email: str = Query(..., description="User email"),
        orcid_id: Optional[str] = Query(None, description="User ORCID ID (optional)"),
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),

):
    """
    Get user activities by email or ORCID ID (optional)

    Example call:
     -> api/users/activities?email=<email>&limit=50&offset=0
    Example outupt:
    [
    {
        "id": 2,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile created/updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-19T16:47:06.076746"
    }
]

------
[
    {
        "id": 7,
        "user_id": null,
        "activity_type": "login",
        "description": "string",
        "meta_data": {
            "additionalProp1": {}
        },
        "ip_address": "127.0.0.1",
        "user_agent": "PostmanRuntime/7.45.0",
        "created_at": "2025-08-20T15:12:41.586364"
    },
    {
        "id": 6,
        "user_id": null,
        "activity_type": "login",
        "description": "string",
        "meta_data": {
            "additionalProp1": {}
        },
        "ip_address": "127.0.0.1",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36",
        "created_at": "2025-08-20T15:07:24.522163"
    },
    {
        "id": 3,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile created/updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-19T17:03:53.243304"
    }
]
    """
    try:
        async with user_db_manager.get_async_session() as session:
            # Get profile by email or ORCID
            profile = await user_profile_repo.get_by_email(session, email)
            if not profile and orcid_id:
                profile = await user_profile_repo.get_by_orcid_id(session, orcid_id)

            if not profile:
                raise HTTPException(status_code=404, detail="Profile not found")

            activities = await user_activity_repo.get_user_activities(
                session=session,
                profile_id=profile.id,
                limit=limit,
                offset=offset
            )

            activities_list = []
            for activity in activities:
                activity_dict = convert_row_to_dict(activity)
                if 'activity_type' in activity_dict and activity_dict['activity_type']:
                    activity_dict['activity_type'] = ActivityType(activity_dict['activity_type'])
                if 'ip_address' in activity_dict and activity_dict['ip_address']:
                    activity_dict['ip_address'] = str(activity_dict['ip_address'])
                activities_list.append(UserActivity(**activity_dict))
            
            return activities_list
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting activities for {email}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/activities/log", response_model=dict)
async def log_activity(
        jwt_user: Annotated[dict, Depends(get_current_user)],
        activity: UserActivity,
        request: Request,
        email: str = Query(..., description="User email"),
        orcid_id: Optional[str] = Query(None, description="User ORCID ID (optional)"),

):
    """Log user activity by email or ORCID ID"""
    try:
        async with user_db_manager.get_async_session() as session:
            # Get profile by email or ORCID
            profile = await user_profile_repo.get_by_email(session, email)
            if not profile and orcid_id:
                profile = await user_profile_repo.get_by_orcid_id(session, orcid_id)

            if not profile:
                raise HTTPException(status_code=404, detail="Profile not found")

            # Get client IP and user agent
            client_ip = request.client.host
            user_agent = request.headers.get("user-agent", "")

            # Log activity
            activity_instance = await user_activity_repo.log_activity(
                session=session,
                profile_id=profile.id,
                activity_type=activity.activity_type,
                description=activity.description,
                meta_data=activity.meta_data,
                ip_address=client_ip,
                user_agent=user_agent
            )

            return {"message": "Activity logged successfully", "activity_id": activity_instance.id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error logging activity for {email}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")


@router.get("/activities", response_model=List[UserActivity])
async def get_activities(
        jwt_user: Annotated[dict, Depends(get_current_user)],
        email: str = Query(..., description="User email"),
        orcid_id: Optional[str] = Query(None, description="User ORCID ID (optional)"),
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),

):
    """
    Get user activities by email or ORCID ID (optional)

    Example call:
     -> api/users/activities?email=<email>&limit=50&offset=0
    Example outupt:
    [
    {
        "id": 42,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T21:41:22.541158"
    },
    {
        "id": 41,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T21:40:28.817681"
    },
    {
        "id": 40,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T21:40:03.772433"
    },
    {
        "id": 39,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T21:38:39.119858"
    },
    {
        "id": 38,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T21:37:48.436143"
    },
    {
        "id": 37,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T21:24:38.620757"
    },
    {
        "id": 36,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T21:23:03.695382"
    },
    {
        "id": 35,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T21:22:13.196854"
    },
    {
        "id": 34,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T21:20:51.056567"
    },
    {
        "id": 33,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T21:18:29.787030"
    },
    {
        "id": 32,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T21:17:41.356626"
    },
    {
        "id": 31,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T21:14:30.902561"
    },
    {
        "id": 30,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T21:10:28.670414"
    },
    {
        "id": 29,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T21:10:10.901745"
    },
    {
        "id": 28,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T21:09:33.921557"
    },
    {
        "id": 27,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T21:08:21.577624"
    },
    {
        "id": 26,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T21:07:18.450464"
    },
    {
        "id": 25,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T21:06:35.850645"
    },
    {
        "id": 24,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T20:55:56.792980"
    },
    {
        "id": 23,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T19:28:38.198257"
    },
    {
        "id": 22,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T19:23:25.163106"
    },
    {
        "id": 21,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T19:23:03.915976"
    },
    {
        "id": 20,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T19:21:43.467008"
    },
    {
        "id": 19,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T19:18:27.057406"
    },
    {
        "id": 18,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T19:16:33.984193"
    },
    {
        "id": 16,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T19:12:15.321527"
    },
    {
        "id": 15,
        "user_id": null,
        "activity_type": "login",
        "description": "string",
        "meta_data": {
            "additionalProp1": {}
        },
        "ip_address": "127.0.0.1",
        "user_agent": "PostmanRuntime/7.45.0",
        "created_at": "2025-08-21T18:54:47.983079"
    },
    {
        "id": 12,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T18:38:39.959016"
    },
    {
        "id": 11,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T18:37:57.496116"
    },
    {
        "id": 10,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T18:33:47.258405"
    },
    {
        "id": 9,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T17:36:27.426550"
    },
    {
        "id": 8,
        "user_id": null,
        "activity_type": "profile_update",
        "description": "Profile created/updated",
        "meta_data": null,
        "ip_address": null,
        "user_agent": null,
        "created_at": "2025-08-21T00:23:08.764484"
    }
]
    """
    try:
        async with user_db_manager.get_async_session() as session:

            profile = await user_profile_repo.get_by_email(session, email)
            if not profile and orcid_id:
                profile = await user_profile_repo.get_by_orcid_id(session, orcid_id)

            if not profile:
                raise HTTPException(status_code=404, detail="Profile not found")

            activities = await user_activity_repo.get_user_activities(
                session=session,
                profile_id=profile.id,
                limit=limit,
                offset=offset
            )
            return [UserActivity(**convert_row_to_dict(activity)) for activity in activities]
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting activities for {email}: {str(e)}")
        raise HTTPException(status_code=500, detail="Internal server error")