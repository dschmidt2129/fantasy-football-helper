from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()

class Player(Base):
    __tablename__ = "players"
    
    id = Column(Integer, primary_key=True, index=True)
    espn_id = Column(Integer, unique=True, index=True)
    name = Column(String, index=True)
    position = Column(String)
    team = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    stats = relationship("PlayerStat", back_populates="player")

class Season(Base):
    __tablename__ = "seasons"
    
    id = Column(Integer, primary_key=True, index=True)
    year = Column(Integer, unique=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class GameWeek(Base):
    __tablename__ = "game_weeks"
    
    id = Column(Integer, primary_key=True, index=True)
    season_id = Column(Integer, ForeignKey("seasons.id"))
    week = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    season = relationship("Season")

class PlayerStat(Base):
    __tablename__ = "player_stats"
    
    id = Column(Integer, primary_key=True, index=True)
    player_id = Column(Integer, ForeignKey("players.id"))
    season_id = Column(Integer, ForeignKey("seasons.id"))
    game_week_id = Column(Integer, ForeignKey("game_weeks.id"))
    points = Column(Float)
    projected_points = Column(Float, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    player = relationship("Player", back_populates="stats")
    season = relationship("Season")
    game_week = relationship("GameWeek")

class ScoringFormat(Base):
    __tablename__ = "scoring_formats"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True)
    description = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
