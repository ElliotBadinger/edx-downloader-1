"""
Test fixtures containing recorded EDX API responses.

This module contains realistic EDX API responses for testing purposes.
These responses are based on the current EDX platform structure as of 2024.
"""

import json
from datetime import datetime, timedelta
from typing import Dict, Any, List


class EdxApiResponseFixtures:
    """Collection of EDX API response fixtures for testing."""
    
    @staticmethod
    def get_login_page_html() -> str:
        """Return HTML content for EDX login page based on real structure."""
        return '''<!DOCTYPE html>
<html lang="en">
<head>
    <title>Login | edX</title>
    <meta name="csrf-token" content="test-csrf-token-12345">
    <meta name="viewport" content="width=device-width, initial-scale=1">
</head>
<body>
    <div class="login-container">
        <div class="login-header">
            <a href="https://www.edx.org">
                <img src="/static/images/edx-logo.svg" alt="edX" />
            </a>
            <h1>Start learning with edX</h1>
        </div>
        <div class="login-form-container">
            <div class="tab-container">
                <div role="tablist">
                    <button role="tab" aria-selected="false">Register</button>
                    <button role="tab" aria-selected="true">Sign in</button>
                </div>
            </div>
            <div class="login-form">
                <form method="post" action="/api/user/v2/account/login_session/">
                    <input type="hidden" name="csrfmiddlewaretoken" value="test-csrf-token-12345">
                    <div class="form-group">
                        <input type="text" name="email_or_username" placeholder="Username or email" required>
                    </div>
                    <div class="form-group">
                        <input type="password" name="password" placeholder="Password" required>
                        <button type="button" class="show-password">Show password</button>
                    </div>
                    <button type="submit" class="btn-primary">Sign in</button>
                    <a href="/reset" class="forgot-password">Forgot password</a>
                </form>
                <div class="social-login">
                    <p>Or sign in with:</p>
                    <a href="https://courses.edx.org/enterprise/login" class="enterprise-login">
                        Company or school credentials
                    </a>
                    <div class="social-buttons">
                        <button class="social-btn apple">Sign in with Apple</button>
                        <button class="social-btn facebook">Sign in with Facebook</button>
                        <button class="social-btn google">Sign in with Google</button>
                        <button class="social-btn microsoft">Sign in with Microsoft</button>
                    </div>
                </div>
            </div>
        </div>
    </div>
</body>
</html>'''

    @staticmethod
    def get_login_success_response() -> Dict[str, Any]:
        """Return successful login API response."""
        return {
            "success": True,
            "redirect_url": "/dashboard",
            "user_id": 12345,
            "username": "test_user",
            "email": "test@example.com"
        }
    
    @staticmethod
    def get_login_error_response() -> Dict[str, Any]:
        """Return failed login API response."""
        return {
            "success": False,
            "value": "Email or password is incorrect.",
            "error_code": "incorrect-email-or-password"
        }
    
    @staticmethod
    def get_csrf_token_response() -> Dict[str, Any]:
        """Return CSRF token API response."""
        return {
            "csrf_token": "test-csrf-token-12345"
        }
    
    @staticmethod
    def get_user_info_response() -> Dict[str, Any]:
        """Return user information API response."""
        return {
            "username": "test_user",
            "email": "test@example.com",
            "name": "Test User",
            "is_active": True,
            "date_joined": "2024-01-15T10:30:00Z",
            "profile": {
                "name": "Test User",
                "country": "US",
                "level_of_education": "m",
                "goals": "Learn new skills"
            }
        }

    @staticmethod
    def get_course_list_response() -> Dict[str, Any]:
        """Return course list API response."""
        return {
            "count": 2,
            "next": None,
            "previous": None,
            "results": [
                {
                    "course_id": "course-v1:MITx+6.00.1x+2T2024",
                    "name": "Introduction to Computer Science and Programming Using Python",
                    "short_description": "Learn to code with Python",
                    "org": "MITx",
                    "number": "6.00.1x",
                    "run": "2T2024",
                    "start": "2024-02-01T00:00:00Z",
                    "end": "2024-05-31T23:59:59Z",
                    "enrollment_start": "2024-01-01T00:00:00Z",
                    "enrollment_end": "2024-02-15T23:59:59Z",
                    "effort": "8-10 hours/week",
                    "pacing": "instructor",
                    "course_image_url": "https://courses.edx.org/asset-v1:MITx+6.00.1x+2T2024+type@asset+block@course_image.jpg",
                    "media": {
                        "course_image": {
                            "uri": "/asset-v1:MITx+6.00.1x+2T2024+type@asset+block@course_image.jpg"
                        },
                        "course_video": {
                            "uri": "https://www.youtube.com/watch?v=example123"
                        }
                    }
                },
                {
                    "course_id": "course-v1:HarvardX+CS50+2024",
                    "name": "CS50: Introduction to Computer Science",
                    "short_description": "Harvard's introduction to computer science",
                    "org": "HarvardX",
                    "number": "CS50",
                    "run": "2024",
                    "start": "2024-01-01T00:00:00Z",
                    "end": "2024-12-31T23:59:59Z",
                    "enrollment_start": "2023-12-01T00:00:00Z",
                    "enrollment_end": None,
                    "effort": "10-20 hours/week",
                    "pacing": "self",
                    "course_image_url": "https://courses.edx.org/asset-v1:HarvardX+CS50+2024+type@asset+block@course_image.jpg",
                    "media": {
                        "course_image": {
                            "uri": "/asset-v1:HarvardX+CS50+2024+type@asset+block@course_image.jpg"
                        }
                    }
                }
            ]
        }

    @staticmethod
    def get_course_outline_response() -> Dict[str, Any]:
        """Return course outline/structure API response."""
        return {
            "root": "block-v1:MITx+6.00.1x+2T2024+type@course+block@course",
            "blocks": {
                "block-v1:MITx+6.00.1x+2T2024+type@course+block@course": {
                    "id": "block-v1:MITx+6.00.1x+2T2024+type@course+block@course",
                    "type": "course",
                    "display_name": "Introduction to Computer Science and Programming Using Python",
                    "children": [
                        "block-v1:MITx+6.00.1x+2T2024+type@chapter+block@week1",
                        "block-v1:MITx+6.00.1x+2T2024+type@chapter+block@week2"
                    ]
                },
                "block-v1:MITx+6.00.1x+2T2024+type@chapter+block@week1": {
                    "id": "block-v1:MITx+6.00.1x+2T2024+type@chapter+block@week1",
                    "type": "chapter",
                    "display_name": "Week 1: Introduction to Python",
                    "children": [
                        "block-v1:MITx+6.00.1x+2T2024+type@sequential+block@lecture1"
                    ]
                },
                "block-v1:MITx+6.00.1x+2T2024+type@sequential+block@lecture1": {
                    "id": "block-v1:MITx+6.00.1x+2T2024+type@sequential+block@lecture1",
                    "type": "sequential",
                    "display_name": "Lecture 1: Introduction",
                    "children": [
                        "block-v1:MITx+6.00.1x+2T2024+type@vertical+block@intro_video"
                    ]
                },
                "block-v1:MITx+6.00.1x+2T2024+type@vertical+block@intro_video": {
                    "id": "block-v1:MITx+6.00.1x+2T2024+type@vertical+block@intro_video",
                    "type": "vertical",
                    "display_name": "Introduction Video",
                    "children": [
                        "block-v1:MITx+6.00.1x+2T2024+type@video+block@video1"
                    ]
                },
                "block-v1:MITx+6.00.1x+2T2024+type@video+block@video1": {
                    "id": "block-v1:MITx+6.00.1x+2T2024+type@video+block@video1",
                    "type": "video",
                    "display_name": "Welcome to 6.00.1x",
                    "student_view_url": "/xblock/block-v1:MITx+6.00.1x+2T2024+type@video+block@video1",
                    "student_view_data": {
                        "duration": 600,
                        "transcripts": {
                            "en": "/api/courses/v1/blocks/block-v1:MITx+6.00.1x+2T2024+type@video+block@video1/handler/transcript/translation/en"
                        },
                        "encoded_videos": {
                            "youtube": {
                                "url": "https://www.youtube.com/watch?v=example123",
                                "file_size": 0
                            },
                            "desktop_mp4": {
                                "url": "https://courses.edx.org/c4x/MITx/6.00.1x/asset/video1_desktop.mp4",
                                "file_size": 52428800
                            },
                            "mobile_low": {
                                "url": "https://courses.edx.org/c4x/MITx/6.00.1x/asset/video1_mobile_low.mp4",
                                "file_size": 20971520
                            }
                        }
                    }
                }
            }
        }

    @staticmethod
    def get_enrollment_response() -> Dict[str, Any]:
        """Return course enrollment API response."""
        return {
            "course_id": "course-v1:MITx+6.00.1x+2T2024",
            "user": "test_user",
            "mode": "audit",
            "is_active": True,
            "created": "2024-01-15T10:30:00Z"
        }
    
    @staticmethod
    def get_video_transcript_response() -> str:
        """Return video transcript content."""
        return '''1
00:00:00,000 --> 00:00:05,000
Welcome to Introduction to Computer Science and Programming Using Python.

2
00:00:05,000 --> 00:00:10,000
In this course, you'll learn the fundamentals of programming.

3
00:00:10,000 --> 00:00:15,000
We'll start with basic concepts and build up to more complex topics.'''
    
    @staticmethod
    def get_error_response_401() -> Dict[str, Any]:
        """Return 401 Unauthorized error response."""
        return {
            "error": "Authentication credentials were not provided.",
            "error_code": "not_authenticated"
        }
    
    @staticmethod
    def get_error_response_403() -> Dict[str, Any]:
        """Return 403 Forbidden error response."""
        return {
            "error": "You do not have permission to perform this action.",
            "error_code": "permission_denied"
        }
    
    @staticmethod
    def get_error_response_404() -> Dict[str, Any]:
        """Return 404 Not Found error response."""
        return {
            "error": "The requested resource was not found.",
            "error_code": "not_found"
        }
    
    @staticmethod
    def get_rate_limit_response() -> Dict[str, Any]:
        """Return rate limit exceeded response."""
        return {
            "error": "Rate limit exceeded. Please try again later.",
            "error_code": "throttled",
            "available_in": 60
        }
    
    @staticmethod
    def get_server_error_response() -> Dict[str, Any]:
        """Return 500 server error response."""
        return {
            "error": "Internal server error occurred.",
            "error_code": "server_error"
        }


class EdxTestDataGenerator:
    """Utility class for generating test data and mock responses."""
    
    @staticmethod
    def generate_course_id(org: str = "TestX", number: str = "TEST101", run: str = "2024") -> str:
        """Generate a realistic course ID."""
        return f"course-v1:{org}+{number}+{run}"
    
    @staticmethod
    def generate_block_id(course_id: str, block_type: str, block_name: str) -> str:
        """Generate a realistic block ID."""
        course_key = course_id.replace("course-v1:", "")
        return f"block-v1:{course_key}+type@{block_type}+block@{block_name}"
    
    @staticmethod
    def generate_video_urls(video_id: str) -> Dict[str, Dict[str, Any]]:
        """Generate realistic video URL structure."""
        return {
            "youtube": {
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "file_size": 0
            },
            "desktop_mp4": {
                "url": f"https://courses.edx.org/c4x/TestX/TEST101/asset/{video_id}_desktop.mp4",
                "file_size": 52428800
            },
            "mobile_low": {
                "url": f"https://courses.edx.org/c4x/TestX/TEST101/asset/{video_id}_mobile_low.mp4",
                "file_size": 20971520
            },
            "desktop_webm": {
                "url": f"https://courses.edx.org/c4x/TestX/TEST101/asset/{video_id}_desktop.webm",
                "file_size": 45678900
            }
        }
    
    @staticmethod
    def generate_course_outline(course_id: str, num_chapters: int = 2, num_videos_per_chapter: int = 2) -> Dict[str, Any]:
        """Generate a realistic course outline structure."""
        course_key = course_id.replace("course-v1:", "")
        root_block_id = f"block-v1:{course_key}+type@course+block@course"
        
        blocks = {
            root_block_id: {
                "id": root_block_id,
                "type": "course",
                "display_name": "Test Course",
                "children": []
            }
        }
        
        for chapter_num in range(1, num_chapters + 1):
            chapter_id = f"block-v1:{course_key}+type@chapter+block@chapter{chapter_num}"
            blocks[root_block_id]["children"].append(chapter_id)
            
            blocks[chapter_id] = {
                "id": chapter_id,
                "type": "chapter",
                "display_name": f"Chapter {chapter_num}",
                "children": []
            }
            
            for video_num in range(1, num_videos_per_chapter + 1):
                sequential_id = f"block-v1:{course_key}+type@sequential+block@seq{chapter_num}_{video_num}"
                vertical_id = f"block-v1:{course_key}+type@vertical+block@vert{chapter_num}_{video_num}"
                video_id = f"block-v1:{course_key}+type@video+block@video{chapter_num}_{video_num}"
                
                blocks[chapter_id]["children"].append(sequential_id)
                
                blocks[sequential_id] = {
                    "id": sequential_id,
                    "type": "sequential",
                    "display_name": f"Lecture {chapter_num}.{video_num}",
                    "children": [vertical_id]
                }
                
                blocks[vertical_id] = {
                    "id": vertical_id,
                    "type": "vertical",
                    "display_name": f"Video Unit {chapter_num}.{video_num}",
                    "children": [video_id]
                }
                
                blocks[video_id] = {
                    "id": video_id,
                    "type": "video",
                    "display_name": f"Video {chapter_num}.{video_num}",
                    "student_view_url": f"/xblock/{video_id}",
                    "student_view_data": {
                        "duration": 600 + (chapter_num * video_num * 100),
                        "transcripts": {
                            "en": f"/api/courses/v1/blocks/{video_id}/handler/transcript/translation/en"
                        },
                        "encoded_videos": EdxTestDataGenerator.generate_video_urls(f"video{chapter_num}_{video_num}")
                    }
                }
        
        return {
            "root": root_block_id,
            "blocks": blocks
        }


class EdxMockResponses:
    """Mock HTTP responses for testing EDX API interactions."""
    
    @staticmethod
    def mock_requests_session():
        """Create a mock requests session with predefined responses."""
        from unittest.mock import Mock, MagicMock
        
        session = Mock()
        
        # Mock login page response
        login_page_response = Mock()
        login_page_response.status_code = 200
        login_page_response.text = EdxApiResponseFixtures.get_login_page_html()
        login_page_response.headers = {'Set-Cookie': 'csrftoken=test-csrf-token-12345'}
        
        # Mock successful login response
        login_success_response = Mock()
        login_success_response.status_code = 200
        login_success_response.json.return_value = EdxApiResponseFixtures.get_login_success_response()
        
        # Mock course list response
        course_list_response = Mock()
        course_list_response.status_code = 200
        course_list_response.json.return_value = EdxApiResponseFixtures.get_course_list_response()
        
        # Mock course outline response
        course_outline_response = Mock()
        course_outline_response.status_code = 200
        course_outline_response.json.return_value = EdxApiResponseFixtures.get_course_outline_response()
        
        # Configure session.get responses
        def mock_get(url, **kwargs):
            if 'login' in url:
                return login_page_response
            elif 'courses' in url and 'blocks' in url:
                return course_outline_response
            elif 'courses' in url:
                return course_list_response
            else:
                # Default response
                response = Mock()
                response.status_code = 404
                response.json.return_value = EdxApiResponseFixtures.get_error_response_404()
                return response
        
        # Configure session.post responses
        def mock_post(url, **kwargs):
            if 'login' in url:
                return login_success_response
            else:
                response = Mock()
                response.status_code = 404
                return response
        
        session.get.side_effect = mock_get
        session.post.side_effect = mock_post
        
        return session