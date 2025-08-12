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

from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError
from fastapi import HTTPException

from core.configuration import config
from core.models.database_models import Base, User, UserProfile, UserActivity, UserContribution, UserRole

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
            echo=False  # Set to True for SQL debugging
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
            echo=False
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
                await session.commit()
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


class UserRepository(UserBaseRepository):
    """User repository for user authentication operations"""
    
    def __init__(self):
        super().__init__(User)
    
    async def get_by_email(self, session: AsyncSession, email: str) -> Optional[User]:
        """Get user by email"""
        try:
            result = await session.execute(
                text('SELECT * FROM "Web_jwtuser" WHERE email = :email AND is_active = true'),
                {"email": email}
            )
            row = result.fetchone()
            if row:
                # Convert raw result to User object
                user = User(
                    id=row.id,
                    full_name=row.full_name,
                    email=row.email,
                    password=row.password,
                    is_active=row.is_active,
                    created_at=row.created_at,
                    updated_at=row.updated_at
                )
                return user
            return None
        except SQLAlchemyError as e:
            logger.error(f"Error getting user by email: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def create_user(self, session: AsyncSession, full_name: str, email: str, password: str) -> User:
        """Create a new user"""
        try:
            user = User(
                full_name=full_name,
                email=email,
                password=password,
                is_active=False
            )
            session.add(user)
            await session.flush()
            await session.refresh(user)
            return user
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error creating user: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def activate_user(self, session: AsyncSession, user_id: int) -> bool:
        """Activate a user account"""
        try:
            user = await session.get(User, user_id)
            if not user:
                return False
            
            user.is_active = True
            user.updated_at = datetime.utcnow()
            await session.flush()
            return True
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error activating user: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def deactivate_user(self, session: AsyncSession, user_id: int) -> bool:
        """Deactivate a user account"""
        try:
            user = await session.get(User, user_id)
            if not user:
                return False
            
            user.is_active = False
            user.updated_at = datetime.utcnow()
            await session.flush()
            return True
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error deactivating user: {str(e)}")
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
    
    async def get_by_user_id(self, session: AsyncSession, user_id: int) -> Optional[UserProfile]:
        """Get profile by user ID"""
        try:
            result = await session.execute(
                text('SELECT * FROM "Web_user_profile" WHERE user_id = :user_id'),
                {"user_id": user_id}
            )
            return result.fetchone()
        except SQLAlchemyError as e:
            logger.error(f"Error getting user profile: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def get_by_email(self, session: AsyncSession, email: str) -> Optional[UserProfile]:
        """Get profile by email"""
        try:
            result = await session.execute(
                text('SELECT * FROM "Web_user_profile" WHERE email = :email'),
                {"email": email}
            )
            return result.fetchone()
        except SQLAlchemyError as e:
            logger.error(f"Error getting user profile by email: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def get_by_orcid_id(self, session: AsyncSession, orcid_id: str) -> Optional[UserProfile]:
        """Get profile by ORCID ID"""
        try:
            result = await session.execute(
                text('SELECT * FROM "Web_user_profile" WHERE orcid_id = :orcid_id'),
                {"orcid_id": orcid_id}
            )
            return result.fetchone()
        except SQLAlchemyError as e:
            logger.error(f"Error getting user profile by ORCID ID: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def create_or_update_profile(self, session: AsyncSession, user_id: int, **profile_data) -> UserProfile:
        """Create or update user profile"""
        try:
            # Check if profile exists
            existing_profile = await self.get_by_user_id(session, user_id)
            
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
                profile_data['user_id'] = user_id
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
    
    async def log_activity(self, session: AsyncSession, profile_id: int, activity_type: str, 
                          description: Optional[str] = None, meta_data: Optional[Dict] = None,
                          ip_address: Optional[str] = None, user_agent: Optional[str] = None) -> UserActivity:
        """Log user activity"""
        try:
            activity = UserActivity(
                profile_id=profile_id,
                activity_type=activity_type,
                description=description,
                meta_data=meta_data,
                ip_address=ip_address,
                user_agent=user_agent
            )
            session.add(activity)
            await session.flush()
            await session.refresh(activity)
            return activity
        except SQLAlchemyError as e:
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
    
    async def get_user_contributions(self, session: AsyncSession, user_id: int, limit: int = 50, offset: int = 0) -> List[UserContribution]:
        """Get user contributions with pagination"""
        try:
            result = await session.execute(
                text("""
                    SELECT * FROM "Web_user_contribution" 
                    WHERE user_id = :user_id 
                    ORDER BY created_at DESC 
                    LIMIT :limit OFFSET :offset
                """),
                {"user_id": user_id, "limit": limit, "offset": offset}
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
    
    async def get_user_roles(self, session: AsyncSession, user_id: int) -> List[str]:
        """Get user roles"""
        try:
            result = await session.execute(
                text('SELECT role FROM "Web_user_role" WHERE user_id = :user_id AND is_active = true'),
                {"user_id": user_id}
            )
            return [row.role for row in result.fetchall()]
        except SQLAlchemyError as e:
            logger.error(f"Error getting user roles: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def assign_role(self, session: AsyncSession, user_id: int, role: str, assigned_by: Optional[int] = None) -> UserRole:
        """Assign role to user"""
        try:
            # Check if role already exists
            existing_role = await session.execute(
                text('SELECT * FROM "Web_user_role" WHERE user_id = :user_id AND role = :role'),
                {"user_id": user_id, "role": role}
            )
            
            if existing_role.fetchone():
                # Update existing role
                await session.execute(
                    text("""
                        UPDATE "Web_user_role" 
                        SET assigned_by = :assigned_by, assigned_at = :assigned_at, is_active = true, updated_at = :updated_at
                        WHERE user_id = :user_id AND role = :role
                    """),
                    {
                        "user_id": user_id,
                        "role": role,
                        "assigned_by": assigned_by,
                        "assigned_at": datetime.utcnow(),
                        "updated_at": datetime.utcnow()
                    }
                )
                await session.flush()
                
                # Get updated role
                result = await session.execute(
                    text('SELECT * FROM "Web_user_role" WHERE user_id = :user_id AND role = :role'),
                    {"user_id": user_id, "role": role}
                )
                return result.fetchone()
            else:
                # Create new role assignment
                user_role = UserRole(
                    user_id=user_id,
                    role=role,
                    assigned_by=assigned_by,
                    is_active=True
                )
                session.add(user_role)
                await session.flush()
                await session.refresh(user_role)
                return user_role
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error assigning role: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def remove_role(self, session: AsyncSession, user_id: int, role: str) -> bool:
        """Remove role from user"""
        try:
            result = await session.execute(
                text("""
                    UPDATE "Web_user_role" 
                    SET is_active = false, updated_at = :updated_at
                    WHERE user_id = :user_id AND role = :role
                """),
                {"user_id": user_id, "role": role, "updated_at": datetime.utcnow()}
            )
            await session.flush()
            return result.rowcount > 0
        except SQLAlchemyError as e:
            await session.rollback()
            logger.error(f"Error removing role: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))
    
    async def get_users_by_role(self, session: AsyncSession, role: str, limit: int = 50, offset: int = 0) -> List[int]:
        """Get user IDs by role"""
        try:
            result = await session.execute(
                text("""
                    SELECT user_id FROM "Web_user_role" 
                    WHERE role = :role AND is_active = true
                    ORDER BY assigned_at DESC 
                    LIMIT :limit OFFSET :offset
                """),
                {"role": role, "limit": limit, "offset": offset}
            )
            return [row.user_id for row in result.fetchall()]
        except SQLAlchemyError as e:
            logger.error(f"Error getting users by role: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))


# User repository instances
user_repo = UserRepository()
user_profile_repo = UserProfileRepository()
user_activity_repo = UserActivityRepository()
user_contribution_repo = UserContributionRepository()
user_role_repo = UserRoleRepository() 