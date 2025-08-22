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

from typing import Optional, List, Dict, Any
from datetime import datetime
import logging
from contextlib import asynccontextmanager

from sqlalchemy import create_engine, text, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError
from fastapi import HTTPException

from core.configuration import config
from core.models.database_models import Base, JWTUser, UserProfile, UserActivity, UserContribution, UserRole, UserCountry, UserOrganization, UserEducation, UserExpertise, AvailableRole, AvailableCountry
from core.models.user import ActivityType, ContributionStatus

logger = logging.getLogger(__name__)


class UserDatabaseManager:
    """User-specific database manager for SQLAlchemy ORM operations"""
    
    def __init__(self):
        self.engine = None
        self.async_engine = None
        self.session_factory = None
        self.async_session_factory = None
    
    def init_sync_engine(self):
        """Initialize synchronous database engine"""
        database_url = f"postgresql://{config.postgres_user}:{config.postgres_password}@{config.postgres_host}:{config.postgres_port}/{config.postgres_database}"
        
        self.engine = create_engine(
            database_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            echo=False  #  True for SQL debugging
        )
        
        self.session_factory = sessionmaker(
            bind=self.engine,
            autocommit=False,
            autoflush=False
        )
    
    def init_async_engine(self):
        """Initialize asynchronous database engine"""
        database_url = f"postgresql+asyncpg://{config.postgres_user}:{config.postgres_password}@{config.postgres_host}:{config.postgres_port}/{config.postgres_database}"
        
        self.async_engine = create_async_engine(
            database_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            echo=True  # Enable SQL logging to see what's happening
        )
        
        self.async_session_factory = async_sessionmaker(
            bind=self.async_engine,
            class_=AsyncSession,
            autocommit=False,
            autoflush=False
        )
    
    def create_user_tables(self):
        """Create all user-related tables"""
        try:
            # Use create_all with checkfirst=True to avoid errors if tables exist
            Base.metadata.create_all(bind=self.engine, checkfirst=True)
            logger.info("User database tables created/verified successfully")
        except Exception as e:
            logger.error(f"Error creating user tables: {str(e)}")
            raise HTTPException(status_code=500, detail=f"User database table creation error: {str(e)}")
    
    def drop_user_tables(self):
        """Drop all user-related tables (use with caution)"""
        try:
            Base.metadata.drop_all(bind=self.engine)
            logger.info("User database tables dropped successfully")
        except Exception as e:
            logger.error(f"Error dropping user tables: {str(e)}")
            raise HTTPException(status_code=500, detail=f"User database table drop error: {str(e)}")
    
    @asynccontextmanager
    async def get_async_session(self):
        """Get async database session"""
        if not self.async_session_factory:
            self.init_async_engine()
        
        async with self.async_session_factory() as session:
            try:
                yield session
                # Don't auto-commit - let the caller handle commits
                # await session.commit()  # Removed auto-commit
            except Exception as e:
                await session.rollback()
                logger.error(f"User database session error: {str(e)}")
                raise
            finally:
                await session.close()
    
    def get_sync_session(self):
        """Get synchronous database session"""
        if not self.session_factory:
            self.init_sync_engine()
        
        return self.session_factory()


# Global user database manager instance
user_db_manager = UserDatabaseManager()


class UserBaseRepository:
    """Base repository class for user-related database operations"""
    
    def __init__(self, model_class):
        self.model = model_class
    
    async def create(self, session: AsyncSession, **kwargs) -> Any:
        """Create a new record"""
        try:
            instance = self.model(**kwargs)
            session.add(instance)
            await session.flush()
            await session.refresh(instance)
            return instance
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error creating {self.model.__name__}: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def get_by_id(self, session: AsyncSession, id: int) -> Optional[Any]:
        """Get record by ID"""
        try:
            return await session.get(self.model, id)
        except SQLAlchemyError as e:
            logger.error(f"Error getting {self.model.__name__} by ID: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def get_all(self, session: AsyncSession, limit: int = 100, offset: int = 0) -> List[Any]:
        """Get all records with pagination"""
        try:
            result = await session.execute(
                text(f"SELECT * FROM {self.model.__tablename__} ORDER BY id DESC LIMIT :limit OFFSET :offset"),
                {"limit": limit, "offset": offset}
            )
            return result.fetchall()
        except SQLAlchemyError as e:
            logger.error(f"Error getting all {self.model.__name__}: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def update(self, session: AsyncSession, id: int, **kwargs) -> Optional[Any]:
        """Update a record"""
        try:
            instance = await session.get(self.model, id)
            if not instance:
                return None
            
            for key, value in kwargs.items():
                if hasattr(instance, key):
                    setattr(instance, key, value)
            
            instance.updated_at = datetime.utcnow()
            await session.flush()
            await session.refresh(instance)
            return instance
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error updating {self.model.__name__}: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def delete(self, session: AsyncSession, id: int) -> bool:
        """Delete a record"""
        try:
            instance = await session.get(self.model, id)
            if not instance:
                return False
            
            await session.delete(instance)
            await session.flush()
            return True
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error deleting {self.model.__name__}: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))


class JWTUserRepository(UserBaseRepository):
    """JWT User repository for JWT authentication operations"""
    
    def __init__(self):
        super().__init__(JWTUser)
    
    async def get_by_email(self, session: AsyncSession, email: str) -> Optional[JWTUser]:
        """Get JWT user by email"""
        try:
            result = await session.execute(
                text('SELECT * FROM "Web_jwtuser" WHERE email = :email AND is_active = true'),
                {"email": email}
            )
            row = result.fetchone()
            if row:
                # Convert raw result to JWTUser object
                jwt_user = JWTUser(
                    id=row.id,
                    full_name=row.full_name,
                    email=row.email,
                    password=row.password,
                    is_active=row.is_active,
                    created_at=row.created_at,
                    updated_at=row.updated_at
                )
                return jwt_user
            return None
        except SQLAlchemyError as e:
            logger.error(f"Error getting JWT user by email: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def create_user(self, session: AsyncSession, full_name: str, email: str, password: str) -> JWTUser:
        """Create a new JWT user"""
        try:
            jwt_user = JWTUser(
                full_name=full_name,
                email=email,
                password=password,
                is_active=False
            )
            session.add(jwt_user)
            await session.flush()
            await session.refresh(jwt_user)
            return jwt_user
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error creating JWT user: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def activate_user(self, session: AsyncSession, user_id: int) -> bool:
        """Activate a JWT user account"""
        try:
            jwt_user = await session.get(JWTUser, user_id)
            if not jwt_user:
                return False
            
            jwt_user.is_active = True
            jwt_user.updated_at = datetime.utcnow()
            await session.flush()
            return True
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error activating JWT user: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def deactivate_user(self, session: AsyncSession, user_id: int) -> bool:
        """Deactivate a JWT user account"""
        try:
            jwt_user = await session.get(JWTUser, user_id)
            if not jwt_user:
                return False
            
            jwt_user.is_active = False
            jwt_user.updated_at = datetime.utcnow()
            await session.flush()
            return True
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error deactivating JWT user: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def get_user_scopes(self, session: AsyncSession, user_id: int) -> List[str]:
        """Get user scopes from database"""
        try:
            result = await session.execute(
                text("""
                    SELECT s.name 
                    FROM "Web_jwtuser_scopes" us
                    JOIN "Web_scope" s ON us.scope_id = s.id
                    WHERE us.jwtuser_id = :user_id
                    ORDER BY s.name
                """),
                {"user_id": user_id}
            )
            scopes = [row.name for row in result.fetchall()]
            return scopes
        except SQLAlchemyError as e:
            logger.error(f"Error getting user scopes: {str(e)}")
            return []


class UserProfileRepository(UserBaseRepository):
    """User profile repository"""
    
    def __init__(self):
        super().__init__(UserProfile)
    

    
    async def get_by_email(self, session: AsyncSession, email: str) -> Optional[UserProfile]:
        """Get profile by email"""
        try:
            result = await session.execute(
                select(UserProfile).where(UserProfile.email == email)
            )
            return result.scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(f"Error getting user profile by email: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def get_by_orcid_id(self, session: AsyncSession, orcid_id: str) -> Optional[UserProfile]:
        """Get profile by ORCID ID"""
        try:
            result = await session.execute(
                select(UserProfile).where(UserProfile.orcid_id == orcid_id)
            )
            return result.scalar_one_or_none()
        except SQLAlchemyError as e:
            logger.error(f"Error getting user profile by ORCID ID: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def create_profile(self, session: AsyncSession, **profile_data) -> UserProfile:
        """Create new user profile"""
        try:
            profile = UserProfile(**profile_data)
            session.add(profile)
            await session.flush()
            await session.refresh(profile)
            return profile
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error creating user profile: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def create_or_update_profile(self, session: AsyncSession, **profile_data) -> UserProfile:
        """Create or update user profile"""
        try:
            # Check if profile exists by email
            email = profile_data.get('email')
            if not email:
                raise HTTPException(status_code=400, detail="Email is required")
            
            existing_profile = await self.get_by_email(session, email)
            
            # Also check by ORCID ID if provided
            orcid_id = profile_data.get('orcid_id')
            if orcid_id and not existing_profile:
                existing_profile = await self.get_by_orcid_id(session, orcid_id)
            
            if existing_profile:
                # Update existing profile
                for key, value in profile_data.items():
                    if hasattr(existing_profile, key):
                        setattr(existing_profile, key, value)
                existing_profile.updated_at = datetime.utcnow()
                await session.flush()
                await session.refresh(existing_profile)
                return existing_profile
            else:
                # Create new profile
                profile = UserProfile(**profile_data)
                session.add(profile)
                await session.flush()
                await session.refresh(profile)
                return profile
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error creating/updating user profile: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def get_profiles_by_role(self, session: AsyncSession, role: str, limit: int = 50, offset: int = 0) -> List[UserProfile]:
        """Get profiles by role"""
        try:
            result = await session.execute(
                text("""
                    SELECT * FROM "Web_user_profile" 
                    WHERE role = :role 
                    ORDER BY created_at DESC 
                    LIMIT :limit OFFSET :offset
                """),
                {"role": role, "limit": limit, "offset": offset}
            )
            return result.fetchall()
        except SQLAlchemyError as e:
            logger.error(f"Error getting profiles by role: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))


class UserActivityRepository(UserBaseRepository):
    """User activity repository"""
    
    def __init__(self):
        super().__init__(UserActivity)
    
    async def get_user_activities(self, session: AsyncSession, profile_id: int, limit: int = 50, offset: int = 0) -> List[UserActivity]:
        """Get user activities with pagination"""
        try:
            result = await session.execute(
                text("""
                    SELECT * FROM "Web_user_activity" 
                    WHERE profile_id = :profile_id 
                    ORDER BY created_at DESC 
                    LIMIT :limit OFFSET :offset
                """),
                {"profile_id": profile_id, "limit": limit, "offset": offset}
            )
            return result.fetchall()
        except SQLAlchemyError as e:
            logger.error(f"Error getting user activities: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def log_activity(self, session: AsyncSession, profile_id: int, activity_type: ActivityType, 
                          description: Optional[str] = None, meta_data: Optional[Dict] = None,
                          ip_address: Optional[str] = None, user_agent: Optional[str] = None,
                          location: Optional[Dict] = None, isp: Optional[str] = None, 
                          as_info: Optional[Dict] = None) -> UserActivity:
        """Log user activity"""
        try:
            from datetime import datetime
            import json
            
            print(f"DEBUG: Starting log_activity for profile_id: {profile_id}")
            
            # Convert dictionaries to JSON strings for PostgreSQL JSONB fields
            meta_data_json = json.dumps(meta_data) if meta_data else None
            location_json = json.dumps(location) if location else None
            as_info_json = json.dumps(as_info) if as_info else None
            
            print(f"DEBUG: JSON conversion completed")
            
            # Use direct SQL insert to avoid ORM issues
            result = await session.execute(text("""
                INSERT INTO "Web_user_activity" 
                (profile_id, activity_type, description, meta_data, ip_address, user_agent, location, isp, as_info, created_at)
                VALUES (:profile_id, :activity_type, :description, :meta_data, :ip_address, :user_agent, :location, :isp, :as_info, :created_at)
                RETURNING id
            """), {
                'profile_id': profile_id,
                'activity_type': activity_type.value,
                'description': description,
                'meta_data': meta_data_json,
                'ip_address': ip_address,
                'user_agent': user_agent,
                'location': location_json,
                'isp': isp,
                'as_info': as_info_json,
                'created_at': datetime.utcnow()
            })
            
            print(f"DEBUG: SQL INSERT executed")
            
            activity_id = result.scalar()
            print(f"DEBUG: Activity ID returned: {activity_id}")
            
            # Return a simple object with just the ID
            class SimpleActivity:
                def __init__(self, activity_id):
                    self.id = activity_id
            
            result_obj = SimpleActivity(activity_id)
            print(f"DEBUG: Returning SimpleActivity object with ID: {result_obj.id}")
            
            return result_obj
        except Exception as e:
            print(f"DEBUG: Exception in log_activity: {e}")
            await session.rollback()
            logger.error(f"Error logging activity: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def get_activities_by_type(self, session: AsyncSession, activity_type: str, limit: int = 50, offset: int = 0) -> List[UserActivity]:
        """Get activities by type"""
        try:
            result = await session.execute(
                text("""
                    SELECT * FROM "Web_user_activity" 
                    WHERE activity_type = :activity_type 
                    ORDER BY created_at DESC 
                    LIMIT :limit OFFSET :offset
                """),
                {"activity_type": activity_type, "limit": limit, "offset": offset}
            )
            return result.fetchall()
        except SQLAlchemyError as e:
            logger.error(f"Error getting activities by type: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def get_recent_activities(self, session: AsyncSession, hours: int = 24) -> List[UserActivity]:
        """Get recent activities within specified hours"""
        try:
            result = await session.execute(
                text("""
                    SELECT * FROM "Web_user_activity" 
                    WHERE created_at >= NOW() - INTERVAL ':hours hours'
                    ORDER BY created_at DESC
                """),
                {"hours": hours}
            )
            return result.fetchall()
        except SQLAlchemyError as e:
            logger.error(f"Error getting recent activities: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))


class UserContributionRepository(UserBaseRepository):
    """User contribution repository"""
    
    def __init__(self):
        super().__init__(UserContribution)
    
    async def get_user_contributions(self, session: AsyncSession, profile_id: int, limit: int = 50, offset: int = 0) -> List[UserContribution]:
        """Get user contributions with pagination"""
        try:
            result = await session.execute(
                text("""
                    SELECT * FROM "Web_user_contribution" 
                    WHERE profile_id = :profile_id 
                    ORDER BY created_at DESC 
                    LIMIT :limit OFFSET :offset
                """),
                {"profile_id": profile_id, "limit": limit, "offset": offset}
            )
            return result.fetchall()
        except SQLAlchemyError as e:
            logger.error(f"Error getting user contributions: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def update_status(self, session: AsyncSession, contribution_id: int, status: str) -> Optional[UserContribution]:
        """Update contribution status"""
        try:
            contribution = await session.get(UserContribution, contribution_id)
            if not contribution:
                return None
            
            contribution.status = status
            contribution.updated_at = datetime.utcnow()
            await session.flush()
            await session.refresh(contribution)
            return contribution
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error updating contribution status: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def get_contributions_by_type(self, session: AsyncSession, contribution_type: str, limit: int = 50, offset: int = 0) -> List[UserContribution]:
        """Get contributions by type"""
        try:
            result = await session.execute(
                text("""
                    SELECT * FROM "Web_user_contribution" 
                    WHERE contribution_type = :contribution_type 
                    ORDER BY created_at DESC 
                    LIMIT :limit OFFSET :offset
                """),
                {"contribution_type": contribution_type, "limit": limit, "offset": offset}
            )
            return result.fetchall()
        except SQLAlchemyError as e:
            logger.error(f"Error getting contributions by type: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def get_contributions_by_status(self, session: AsyncSession, status: str, limit: int = 50, offset: int = 0) -> List[UserContribution]:
        """Get contributions by status"""
        try:
            result = await session.execute(
                text("""
                    SELECT * FROM "Web_user_contribution" 
                    WHERE status = :status 
                    ORDER BY created_at DESC 
                    LIMIT :limit OFFSET :offset
                """),
                {"status": status, "limit": limit, "offset": offset}
            )
            return result.fetchall()
        except SQLAlchemyError as e:
            logger.error(f"Error getting contributions by status: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))


class UserRoleRepository(UserBaseRepository):
    """User role repository"""
    
    def __init__(self):
        super().__init__(UserRole)
    
    async def get_user_roles(self, session: AsyncSession, profile_id: int) -> List[UserRole]:
        """Get user roles as UserRole objects"""
        try:
            result = await session.execute(
                select(UserRole).where(UserRole.profile_id == profile_id, UserRole.is_active == True).order_by(UserRole.assigned_at.desc())
            )
            return result.scalars().all()
        except SQLAlchemyError as e:
            logger.error(f"Error getting user roles: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def get_user_role_names(self, session: AsyncSession, profile_id: int) -> List[str]:
        """Get user role names as strings"""
        try:
            result = await session.execute(
                text('SELECT role FROM "Web_user_role" WHERE profile_id = :profile_id AND is_active = true'),
                {"profile_id": profile_id}
            )
            return [row.role for row in result.fetchall()]
        except SQLAlchemyError as e:
            logger.error(f"Error getting user role names: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def assign_role(self, session: AsyncSession, profile_id: int, role: str, assigned_by: Optional[int] = None, is_active: bool = True, expires_at: Optional[datetime] = None) -> UserRole:
        """Assign role to user"""
        try:
            # Check if role already exists
            existing_role = await session.execute(
                text('SELECT * FROM "Web_user_role" WHERE profile_id = :profile_id AND role = :role'),
                {"profile_id": profile_id, "role": role}
            )
            
            if existing_role.fetchone():
                # Update existing role
                await session.execute(
                    text("""
                        UPDATE "Web_user_role" 
                        SET assigned_by = :assigned_by, assigned_at = :assigned_at, is_active = :is_active, expires_at = :expires_at, updated_at = :updated_at
                        WHERE profile_id = :profile_id AND role = :role
                    """),
                    {
                        "profile_id": profile_id,
                        "role": role,
                        "assigned_by": assigned_by,
                        "assigned_at": datetime.utcnow(),
                        "is_active": is_active,
                        "expires_at": expires_at,
                        "updated_at": datetime.utcnow()
                    }
                )
                await session.flush()
                
                # Get updated role
                result = await session.execute(
                    text('SELECT * FROM "Web_user_role" WHERE profile_id = :profile_id AND role = :role'),
                    {"profile_id": profile_id, "role": role}
                )
                return result.fetchone()
            else:
                # Create new role assignment
                user_role = UserRole(
                    profile_id=profile_id,
                    role=role,
                    assigned_by=assigned_by,
                    is_active=is_active,
                    expires_at=expires_at
                )
                session.add(user_role)
                await session.flush()
                await session.refresh(user_role)
                return user_role
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error assigning role: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def remove_role(self, session: AsyncSession, profile_id: int, role: str) -> bool:
        """Remove role from user"""
        try:
            result = await session.execute(
                text("""
                    UPDATE "Web_user_role" 
                    SET is_active = false, updated_at = :updated_at
                    WHERE profile_id = :profile_id AND role = :role
                """),
                {"profile_id": profile_id, "role": role, "updated_at": datetime.utcnow()}
            )
            await session.flush()
            return result.rowcount > 0
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error removing role: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def remove_all_roles(self, session: AsyncSession, profile_id: int) -> bool:
        """Remove all roles for user"""
        try:
            logger.info(f"Removing all roles for profile_id: {profile_id}")
            result = await session.execute(
                text('DELETE FROM "Web_user_role" WHERE profile_id = :profile_id'),
                {"profile_id": profile_id}
            )
            await session.flush()
            logger.info(f"Removed {result.rowcount} roles for profile_id: {profile_id}")
            return result.rowcount > 0
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error removing all roles: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def get_users_by_role(self, session: AsyncSession, role: str, limit: int = 50, offset: int = 0) -> List[int]:
        """Get profile IDs by role"""
        try:
            result = await session.execute(
                text("""
                    SELECT profile_id FROM "Web_user_role" 
                    WHERE role = :role AND is_active = true
                    ORDER BY assigned_at DESC 
                    LIMIT :limit OFFSET :offset
                """),
                {"role": role, "limit": limit, "offset": offset}
            )
            return [row.profile_id for row in result.fetchall()]
        except SQLAlchemyError as e:
            logger.error(f"Error getting users by role: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))


class UserCountryRepository(UserBaseRepository):
    """User country repository"""
    
    def __init__(self):
        super().__init__(UserCountry)
    
    async def get_user_countries(self, session: AsyncSession, profile_id: int) -> List[UserCountry]:
        """Get user countries"""
        try:
            result = await session.execute(
                select(UserCountry).where(UserCountry.profile_id == profile_id).order_by(UserCountry.is_primary.desc(), UserCountry.created_at.asc())
            )
            return result.scalars().all()
        except SQLAlchemyError as e:
            logger.error(f"Error getting user countries: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def add_country(self, session: AsyncSession, profile_id: int, country: str, is_primary: bool = False) -> UserCountry:
        """Add country to user"""
        try:
            # If this is primary, unset other primary countries
            if is_primary:
                await session.execute(
                    text('UPDATE "Web_user_country" SET is_primary = false WHERE profile_id = :profile_id'),
                    {"profile_id": profile_id}
                )
            
            user_country = UserCountry(
                profile_id=profile_id,
                country=country,
                is_primary=is_primary
            )
            session.add(user_country)
            await session.flush()
            await session.refresh(user_country)
            return user_country
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error adding country: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def remove_country(self, session: AsyncSession, profile_id: int, country: str) -> bool:
        """Remove country from user"""
        try:
            result = await session.execute(
                text('DELETE FROM "Web_user_country" WHERE profile_id = :profile_id AND country = :country'),
                {"profile_id": profile_id, "country": country}
            )
            await session.flush()
            return result.rowcount > 0
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error removing country: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def set_primary_country(self, session: AsyncSession, profile_id: int, country: str) -> bool:
        """Set primary country for user"""
        try:
            # Unset all primary countries
            await session.execute(
                text('UPDATE "Web_user_country" SET is_primary = false WHERE profile_id = :profile_id'),
                {"profile_id": profile_id}
            )
            
            # Set the specified country as primary
            result = await session.execute(
                text('UPDATE "Web_user_country" SET is_primary = true WHERE profile_id = :profile_id AND country = :country'),
                {"profile_id": profile_id, "country": country}
            )
            await session.flush()
            return result.rowcount > 0
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error setting primary country: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def remove_all_countries(self, session: AsyncSession, profile_id: int) -> bool:
        """Remove all countries for user"""
        try:
            result = await session.execute(
                text('DELETE FROM "Web_user_country" WHERE profile_id = :profile_id'),
                {"profile_id": profile_id}
            )
            await session.flush()
            return result.rowcount > 0
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error removing all countries: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))


class UserExpertiseRepository(UserBaseRepository):
    """User expertise repository"""
    
    def __init__(self):
        super().__init__(UserExpertise)
    
    async def get_user_expertise(self, session: AsyncSession, profile_id: int) -> List[UserExpertise]:
        """Get user expertise areas"""
        try:
            result = await session.execute(
                select(UserExpertise).where(UserExpertise.profile_id == profile_id).order_by(UserExpertise.created_at.asc())
            )
            return result.scalars().all()
        except SQLAlchemyError as e:
            logger.error(f"Error getting user expertise: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def add_expertise(self, session: AsyncSession, profile_id: int, expertise_area: str, level: Optional[str] = None, years_experience: Optional[int] = None) -> UserExpertise:
        """Add expertise area to user"""
        try:
            user_expertise = UserExpertise(
                profile_id=profile_id,
                expertise_area=expertise_area,
                level=level,
                years_experience=years_experience
            )
            session.add(user_expertise)
            await session.flush()
            await session.refresh(user_expertise)
            return user_expertise
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error adding expertise: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def remove_expertise(self, session: AsyncSession, profile_id: int, expertise_area: str) -> bool:
        """Remove expertise area from user"""
        try:
            result = await session.execute(
                text('DELETE FROM "Web_user_expertise" WHERE profile_id = :profile_id AND expertise_area = :expertise_area'),
                {"profile_id": profile_id, "expertise_area": expertise_area}
            )
            await session.flush()
            return result.rowcount > 0
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error removing expertise: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def update_expertise(self, session: AsyncSession, profile_id: int, expertise_area: str, level: Optional[str] = None, years_experience: Optional[int] = None) -> bool:
        """Update expertise area for user"""
        try:
            result = await session.execute(
                text("""
                    UPDATE "Web_user_expertise" 
                    SET level = :level, years_experience = :years_experience
                    WHERE profile_id = :profile_id AND expertise_area = :expertise_area
                """),
                {
                    "profile_id": profile_id,
                    "expertise_area": expertise_area,
                    "level": level,
                    "years_experience": years_experience
                }
            )
            await session.flush()
            return result.rowcount > 0
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error updating expertise: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def remove_all_expertise(self, session: AsyncSession, profile_id: int) -> bool:
        """Remove all expertise areas for user"""
        try:
            result = await session.execute(
                text('DELETE FROM "Web_user_expertise" WHERE profile_id = :profile_id'),
                {"profile_id": profile_id}
            )
            await session.flush()
            return result.rowcount > 0
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error removing all expertise areas: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))


class UserOrganizationRepository(UserBaseRepository):
    """User organization repository"""
    
    def __init__(self):
        super().__init__(UserOrganization)
    
    async def get_user_organizations(self, session: AsyncSession, profile_id: int) -> List[UserOrganization]:
        """Get user organizations"""
        try:
            result = await session.execute(
                select(UserOrganization).where(UserOrganization.profile_id == profile_id).order_by(UserOrganization.is_primary.desc(), UserOrganization.created_at.asc())
            )
            return result.scalars().all()
        except SQLAlchemyError as e:
            logger.error(f"Error getting user organizations: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def add_organization(self, session: AsyncSession, profile_id: int, organization: str, position: Optional[str] = None, department: Optional[str] = None, is_primary: bool = False, start_date: Optional[datetime] = None, end_date: Optional[datetime] = None) -> UserOrganization:
        """Add organization to user"""
        try:
            logger.info(f"Adding organization '{organization}' for profile_id: {profile_id}")
            # If this is primary, unset other primary organizations
            if is_primary:
                await session.execute(
                    text('UPDATE "Web_user_organization" SET is_primary = false WHERE profile_id = :profile_id'),
                    {"profile_id": profile_id}
                )
            
            user_organization = UserOrganization(
                profile_id=profile_id,
                organization=organization,
                position=position,
                department=department,
                is_primary=is_primary,
                start_date=start_date,
                end_date=end_date
            )
            session.add(user_organization)
            await session.flush()
            await session.refresh(user_organization)
            logger.info(f"Successfully added organization with ID: {user_organization.id}")
            return user_organization
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error adding organization: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def remove_organization(self, session: AsyncSession, profile_id: int, organization: str) -> bool:
        """Remove organization from user"""
        try:
            result = await session.execute(
                text('DELETE FROM "Web_user_organization" WHERE profile_id = :profile_id AND organization = :organization'),
                {"profile_id": profile_id, "organization": organization}
            )
            await session.flush()
            return result.rowcount > 0
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error removing organization: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def remove_all_organizations(self, session: AsyncSession, profile_id: int) -> bool:
        """Remove all organizations for user"""
        try:
            logger.info(f"Removing all organizations for profile_id: {profile_id}")
            result = await session.execute(
                text('DELETE FROM "Web_user_organization" WHERE profile_id = :profile_id'),
                {"profile_id": profile_id}
            )
            await session.flush()
            logger.info(f"Removed {result.rowcount} organizations for profile_id: {profile_id}")
            return result.rowcount > 0
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error removing all organizations: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))


class UserEducationRepository(UserBaseRepository):
    """User education repository"""
    
    def __init__(self):
        super().__init__(UserEducation)
    
    async def get_user_education(self, session: AsyncSession, profile_id: int) -> List[UserEducation]:
        """Get user education history"""
        try:
            result = await session.execute(
                select(UserEducation).where(UserEducation.profile_id == profile_id).order_by(UserEducation.is_primary.desc(), UserEducation.graduation_year.desc(), UserEducation.created_at.asc())
            )
            return result.scalars().all()
        except SQLAlchemyError as e:
            logger.error(f"Error getting user education: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def add_education(self, session: AsyncSession, profile_id: int, degree: str, field_of_study: str, institution: str, graduation_year: Optional[int] = None, is_primary: bool = False) -> UserEducation:
        """Add education to user"""
        try:
            # If this is primary, unset other primary education
            if is_primary:
                await session.execute(
                    text('UPDATE "Web_user_education" SET is_primary = false WHERE profile_id = :profile_id'),
                    {"profile_id": profile_id}
                )
            
            user_education = UserEducation(
                profile_id=profile_id,
                degree=degree,
                field_of_study=field_of_study,
                institution=institution,
                graduation_year=graduation_year,
                is_primary=is_primary
            )
            session.add(user_education)
            await session.flush()
            await session.refresh(user_education)
            return user_education
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error adding education: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def remove_education(self, session: AsyncSession, profile_id: int, degree: str, institution: str) -> bool:
        """Remove education from user"""
        try:
            result = await session.execute(
                text('DELETE FROM "Web_user_education" WHERE profile_id = :profile_id AND degree = :degree AND institution = :institution'),
                {"profile_id": profile_id, "degree": degree, "institution": institution}
            )
            await session.flush()
            return result.rowcount > 0
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error removing education: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def remove_all_education(self, session: AsyncSession, profile_id: int) -> bool:
        """Remove all education for user"""
        try:
            logger.info(f"Removing all education for profile_id: {profile_id}")
            result = await session.execute(
                text('DELETE FROM "Web_user_education" WHERE profile_id = :profile_id'),
                {"profile_id": profile_id}
            )
            await session.flush()
            logger.info(f"Removed {result.rowcount} education records for profile_id: {profile_id}")
            return result.rowcount > 0
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error removing all education: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))


class AvailableRoleRepository(UserBaseRepository):
    """Available role repository for management"""
    
    def __init__(self):
        super().__init__(AvailableRole)
    
    async def get_active_roles(self, session: AsyncSession) -> List[AvailableRole]:
        """Get all active roles"""
        try:
            result = await session.execute(
                text('SELECT * FROM "Web_available_role" WHERE is_active = true ORDER BY category, name'),
            )
            roles = []
            for row in result.fetchall():
                role = AvailableRole()
                role.id = row.id
                role.name = row.name
                role.description = row.description
                role.category = row.category
                role.is_active = row.is_active
                role.created_at = row.created_at
                role.updated_at = row.updated_at
                roles.append(role)
            return roles
        except SQLAlchemyError as e:
            logger.error(f"Error getting active roles: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def get_roles_by_category(self, session: AsyncSession, category: str) -> List[AvailableRole]:
        """Get roles by category"""
        try:
            result = await session.execute(
                text('SELECT * FROM "Web_available_role" WHERE category = :category AND is_active = true ORDER BY name'),
                {"category": category}
            )
            roles = []
            for row in result.fetchall():
                role = AvailableRole()
                role.id = row.id
                role.name = row.name
                role.description = row.description
                role.category = row.category
                role.is_active = row.is_active
                role.created_at = row.created_at
                role.updated_at = row.updated_at
                roles.append(role)
            return roles
        except SQLAlchemyError as e:
            logger.error(f"Error getting roles by category: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def update_by_name(self, session: AsyncSession, name: str, **kwargs) -> Optional[AvailableRole]:
        """Update role by name"""
        try:
            result = await session.execute(
                text('SELECT * FROM "Web_available_role" WHERE name = :name'),
                {"name": name}
            )
            row = result.fetchone()
            if not row:
                return None
            
            # Update the role
            update_fields = []
            params = {"name": name}
            for key, value in kwargs.items():
                if key in ['description', 'category', 'is_active']:
                    update_fields.append(f"{key} = :{key}")
                    params[key] = value
            
            if update_fields:
                update_fields.append("updated_at = :updated_at")
                params["updated_at"] = datetime.utcnow()
                
                await session.execute(
                    text(f'UPDATE "Web_available_role" SET {", ".join(update_fields)} WHERE name = :name'),
                    params
                )
                await session.flush()
            
            # Get updated role
            result = await session.execute(
                text('SELECT * FROM "Web_available_role" WHERE name = :name'),
                {"name": name}
            )
            row = result.fetchone()
            if row:
                role = AvailableRole()
                role.id = row.id
                role.name = row.name
                role.description = row.description
                role.category = row.category
                role.is_active = row.is_active
                role.created_at = row.created_at
                role.updated_at = row.updated_at
                return role
            return None
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error updating role by name: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def delete_by_name(self, session: AsyncSession, name: str) -> bool:
        """Delete role by name"""
        try:
            result = await session.execute(
                text('DELETE FROM "Web_available_role" WHERE name = :name'),
                {"name": name}
            )
            await session.flush()
            return result.rowcount > 0
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error deleting role by name: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))


class AvailableCountryRepository(UserBaseRepository):
    """Available country repository for management"""
    
    def __init__(self):
        super().__init__(AvailableCountry)
    
    async def get_active_countries(self, session: AsyncSession) -> List[AvailableCountry]:
        """Get all active countries"""
        try:
            result = await session.execute(
                text('SELECT * FROM "Web_available_country" WHERE is_active = true ORDER BY region, name'),
            )
            countries = []
            for row in result.fetchall():
                country = AvailableCountry()
                country.id = row.id
                country.name = row.name
                country.code = row.code
                country.code_2 = row.code_2
                country.region = row.region
                country.is_active = row.is_active
                country.created_at = row.created_at
                country.updated_at = row.updated_at
                countries.append(country)
            return countries
        except SQLAlchemyError as e:
            logger.error(f"Error getting active countries: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def get_countries_by_region(self, session: AsyncSession, region: str) -> List[AvailableCountry]:
        """Get countries by region"""
        try:
            result = await session.execute(
                text('SELECT * FROM "Web_available_country" WHERE region = :region AND is_active = true ORDER BY name'),
                {"region": region}
            )
            countries = []
            for row in result.fetchall():
                country = AvailableCountry()
                country.id = row.id
                country.name = row.name
                country.code = row.code
                country.code_2 = row.code_2
                country.region = row.region
                country.is_active = row.is_active
                country.created_at = row.created_at
                country.updated_at = row.updated_at
                countries.append(country)
            return countries
        except SQLAlchemyError as e:
            logger.error(f"Error getting countries by region: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def update_by_name(self, session: AsyncSession, name: str, **kwargs) -> Optional[AvailableCountry]:
        """Update country by name"""
        try:
            result = await session.execute(
                text('SELECT * FROM "Web_available_country" WHERE name = :name'),
                {"name": name}
            )
            row = result.fetchone()
            if not row:
                return None
            
            # Update the country
            update_fields = []
            params = {"name": name}
            for key, value in kwargs.items():
                if key in ['code', 'code_2', 'region', 'is_active']:
                    update_fields.append(f"{key} = :{key}")
                    params[key] = value
            
            if update_fields:
                update_fields.append("updated_at = :updated_at")
                params["updated_at"] = datetime.utcnow()
                
                await session.execute(
                    text(f'UPDATE "Web_available_country" SET {", ".join(update_fields)} WHERE name = :name'),
                    params
                )
                await session.flush()
            
            # Get updated country
            result = await session.execute(
                text('SELECT * FROM "Web_available_country" WHERE name = :name'),
                {"name": name}
            )
            row = result.fetchone()
            if row:
                country = AvailableCountry()
                country.id = row.id
                country.name = row.name
                country.code = row.code
                country.code_2 = row.code_2
                country.region = row.region
                country.is_active = row.is_active
                country.created_at = row.created_at
                country.updated_at = row.updated_at
                return country
            return None
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error updating country by name: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def delete_by_name(self, session: AsyncSession, name: str) -> bool:
        """Delete country by name"""
        try:
            result = await session.execute(
                text('DELETE FROM "Web_available_country" WHERE name = :name'),
                {"name": name}
            )
            await session.flush()
            return result.rowcount > 0
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error deleting country by name: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))


# Repository instances
jwt_user_repo = JWTUserRepository()
user_profile_repo = UserProfileRepository()
user_activity_repo = UserActivityRepository()
user_contribution_repo = UserContributionRepository()
user_role_repo = UserRoleRepository()
user_country_repo = UserCountryRepository()
user_organization_repo = UserOrganizationRepository()
user_education_repo = UserEducationRepository()
user_expertise_repo = UserExpertiseRepository()
available_role_repo = AvailableRoleRepository()
available_country_repo = AvailableCountryRepository() 