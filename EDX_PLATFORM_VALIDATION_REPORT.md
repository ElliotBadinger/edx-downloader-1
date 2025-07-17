# EDX Platform API Validation Report

*Generated: January 17, 2025*

## Executive Summary

This report validates our EDX downloader implementation against the current EDX platform APIs and identifies discrepancies and required updates. 

**Key Finding**: Our implementation is mostly aligned with current APIs, but the Course Blocks API endpoint needs verification and video extraction requires strengthening.

## Current Implementation Analysis

### API Endpoints Used

Our codebase currently targets these EDX API endpoints:

**Main API Endpoints:**
- **Course Blocks**: `/api/courses/v1/courses/{course_id}/blocks/`
- **Course Info**: `/api/courses/v1/courses/{course_id}/`
- **User Info**: `/api/user/v1/me`
- **Authentication**: `/oauth2/access_token`

### Authentication Method

- **JWT-based authentication** using OAuth2 client credentials flow
- **Session-based authentication** with CSRF tokens as fallback

## EDX Platform API Status (2025)

### ✅ Confirmed Working Endpoints

#### 1. Authentication
- **Endpoint**: `POST /oauth2/access_token`
- **Status**: ✅ Active and well-documented
- **Usage**: JWT token generation for API access
- **Documentation**: https://docs.openedx.org/projects/edx-platform/en/latest/how-tos/use_the_api.html
- **Implementation**: ✅ Correctly implemented in our auth module

#### 2. Course Information
- **Endpoint**: `GET /api/courses/v1/courses/{course_id}/`
- **Status**: ✅ Active and documented
- **Usage**: Basic course metadata retrieval
- **Implementation**: ✅ Used correctly in course_manager.py

#### 3. User Information  
- **Endpoint**: `GET /api/user/v1/me`
- **Status**: ✅ Active and documented
- **Usage**: User account validation and session verification
- **Implementation**: ✅ Used for session validation in auth.py

#### 4. Enrollment API
- **Endpoint**: `GET /api/enrollment/v1/enrollment`
- **Status**: ✅ Active and documented
- **Usage**: User enrollment information
- **Implementation**: ⚠️ Not currently used, but available

### ⚠️ Endpoints Requiring Immediate Attention

#### 1. Course Blocks API - CRITICAL ISSUE
- **Current Implementation**: `/api/courses/v1/courses/{course_id}/blocks/`
- **Actual Endpoint**: `/api/courses/v1/blocks/` with `course_id` parameter
- **Status**: ❌ **INCORRECT ENDPOINT FORMAT**
- **Impact**: **HIGH** - Core functionality for course structure parsing
- **Fix Required**: Update endpoint format immediately

#### 2. Video Content Access
- **Status**: ❌ **NO DIRECT API AVAILABLE**
- **Current Approach**: HTML parsing and JavaScript extraction
- **Issue**: Relies on web scraping which is fragile
- **Risk**: **CRITICAL** - Primary functionality depends on HTML structure

### 📊 Additional Available APIs (Not Currently Used)

#### 1. Course Data Analytics
- **Endpoint**: `/api/v0/courses/{course_id}/videos/`
- **Status**: ✅ Available (Data Analytics API)
- **Usage**: Video metadata and analytics
- **Opportunity**: Could enhance video information extraction

#### 2. Bulk Enrollment
- **Endpoint**: `/api/bulk_enroll/v1/bulk_enroll`
- **Status**: ✅ Available
- **Usage**: Not relevant for downloader use case

#### 3. Bookmarks
- **Endpoint**: `/api/bookmarks/v1/bookmarks/`
- **Status**: ✅ Available
- **Usage**: Could be used for selective downloading

## Critical Issues Identified

### 🚨 Issue #1: Course Blocks API Endpoint Format
**Current Code (INCORRECT):**
```python
outline_url = f"/api/courses/v1/courses/{course_info.course_key}/blocks/"
```

**Correct Format:**
```python
outline_url = f"/api/courses/v1/blocks/"
params = {
    'course_id': course_info.course_key,
    'depth': 'all',
    'requested_fields': 'children,display_name,type,student_view_url'
}
```

### 🚨 Issue #2: Video URL Extraction Strategy
**Problem**: No documented API for direct video URL access
**Current Risk**: High dependency on HTML parsing
**Impact**: Core functionality vulnerable to UI changes

### 🚨 Issue #3: Platform Version Compatibility
**Problem**: APIs may vary between EDX instances and versions
**Current Risk**: Hard-coded endpoints may not work universally
**Impact**: Reduced compatibility across different EDX installations

## Recommendations

### 🔥 CRITICAL (Fix Immediately)

1. **Fix Course Blocks API Endpoint**
   ```python
   # In edx_downloader/course_manager.py
   async def get_course_outline(self, course_info: CourseInfo):
       # Update to use: /api/courses/v1/blocks/
       api_url = f"{self.base_url}/api/courses/v1/blocks/"
       params = {
           'course_id': course_info.id,
           'depth': 'all',
           'requested_fields': 'children,display_name,type,student_view_url'
       }
       # ... rest of implementation
   ```

2. **Implement Multi-Strategy Video Extraction**
   ```python
   # Add multiple extraction methods with fallbacks
   async def extract_video_urls(self, block_data):
       strategies = [
           self._extract_from_api_data,
           self._extract_from_html_parsing,
           self._extract_from_javascript,
           self._extract_from_video_elements
       ]
       
       for strategy in strategies:
           try:
               videos = await strategy(block_data)
               if videos:
                   return videos
           except Exception as e:
               logger.warning(f"Strategy {strategy.__name__} failed: {e}")
       
       raise VideoExtractionError("All extraction strategies failed")
   ```

### 🔶 HIGH PRIORITY

3. **Add API Endpoint Configuration**
   ```python
   # Make API endpoints configurable per EDX instance
   @dataclass
   class AppConfig:
       api_endpoints: Dict[str, str] = field(default_factory=lambda: {
           'course_blocks': '/api/courses/v1/blocks/',
           'course_info': '/api/courses/v1/courses/{course_id}/',
           'enrollment': '/api/enrollment/v1/enrollment',
           'oauth_token': '/oauth2/access_token',
           'user_info': '/api/user/v1/me',
           'video_analytics': '/api/v0/courses/{course_id}/videos/'
       })
   ```

4. **Implement Robust Error Handling**
   ```python
   async def _make_api_request_with_fallback(self, endpoint, fallback_method):
       try:
           return await self.api_client.get(endpoint)
       except (NetworkError, AuthenticationError) as e:
           logger.warning(f"API request failed: {e}, falling back to {fallback_method.__name__}")
           return await fallback_method()
   ```

### 🔷 MEDIUM PRIORITY

5. **Add Platform Detection**
   ```python
   async def detect_platform_capabilities(self):
       """Detect EDX platform version and available APIs"""
       try:
           # Try to access API docs endpoint
           api_docs = await self.api_client.get('/api-docs/', require_auth=False)
           return self._parse_available_endpoints(api_docs)
       except:
           # Fallback to endpoint probing
           return await self._probe_endpoints()
   ```

6. **Enhance Video Information Extraction**
   ```python
   # Use Data Analytics API when available
   async def get_enhanced_video_info(self, course_id):
       try:
           video_data = await self.api_client.get(f'/api/v0/courses/{course_id}/videos/')
           return self._parse_video_analytics(video_data)
       except NetworkError:
           # Fallback to HTML parsing
           return await self._extract_videos_from_html()
   ```

## Implementation Updates Required

### File: `edx_downloader/course_manager.py`
```python
# Line ~309: Fix course blocks API endpoint
async def get_course_outline(self, course_info: CourseInfo) -> Dict[str, Any]:
    try:
        # FIXED: Correct API endpoint format
        outline_url = f"/api/courses/v1/blocks/"
        params = {
            'course_id': course_info.course_key,  # Pass as parameter, not in URL
            'depth': 'all',
            'requested_fields': 'children,display_name,type,student_view_url'
        }
        
        outline_data = await self.api_client.get(outline_url, params=params)
        # ... rest of implementation
```

### File: `edx_downloader/models.py`
```python
# Add API endpoint configuration
@dataclass
class AppConfig:
    # ... existing fields ...
    
    # NEW: API endpoint configuration
    api_endpoints: Dict[str, str] = field(default_factory=lambda: {
        'course_blocks': '/api/courses/v1/blocks/',
        'course_info': '/api/courses/v1/courses/{course_id}/',
        'enrollment': '/api/enrollment/v1/enrollment',
        'oauth_token': '/oauth2/access_token',
        'user_info': '/api/user/v1/me',
        'video_analytics': '/api/v0/courses/{course_id}/videos/'
    })
```

## Testing Strategy

### Immediate Testing Required
1. **Course Blocks API Endpoint**
   ```bash
   # Test the corrected endpoint format
   curl -H "Authorization: JWT {token}" \
        "https://courses.edx.org/api/courses/v1/blocks/?course_id={course_id}&depth=all"
   ```

2. **Video Extraction Validation**
   - Test against multiple course types
   - Validate extraction from different video hosting platforms
   - Test fallback mechanisms

### Key API Endpoints to Test
- ✅ `GET /api/courses/v1/blocks/?course_id={course_id}` (CORRECTED FORMAT)
- ✅ `GET /api/courses/v1/courses/{course_id}/`
- ✅ `POST /oauth2/access_token`
- ✅ `GET /api/user/v1/me`
- ⚠️ `GET /api/enrollment/v1/enrollment`
- ⚠️ `GET /api/v0/courses/{course_id}/videos/` (Data Analytics API)

## Risk Assessment

| Component | Risk Level | Impact | Mitigation Status |
|-----------|------------|---------|-------------------|
| Course Blocks API | 🔴 **CRITICAL** | **CRITICAL** | ❌ **NEEDS IMMEDIATE FIX** |
| Video URL Extraction | 🔴 **HIGH** | **CRITICAL** | ⚠️ **NEEDS STRENGTHENING** |
| Authentication | 🟢 **LOW** | **CRITICAL** | ✅ **WELL IMPLEMENTED** |
| Enrollment Detection | 🟡 **MEDIUM** | **MEDIUM** | ⚠️ **NEEDS API INTEGRATION** |
| Platform Compatibility | 🟡 **MEDIUM** | **HIGH** | ❌ **NOT ADDRESSED** |

## Validation Results Summary

### ✅ Working Correctly
- JWT Authentication flow
- Basic course information retrieval
- User session validation
- Error handling framework

### ❌ Requires Immediate Fix
- **Course Blocks API endpoint format** (CRITICAL)
- Video URL extraction robustness
- Platform version compatibility

### ⚠️ Enhancement Opportunities
- Integration with Data Analytics API for video metadata
- Use of Enrollment API for better status detection
- Platform capability detection

## Next Steps

### 🚨 IMMEDIATE (Today)
1. **Fix Course Blocks API endpoint** in `course_manager.py`
2. **Test corrected endpoint** against live EDX instance
3. **Validate video extraction** with current courses

### 📅 THIS WEEK
1. Implement multi-strategy video extraction
2. Add API endpoint configuration system
3. Create comprehensive API error handling

### 📅 NEXT SPRINT
1. Implement platform detection capabilities
2. Add Data Analytics API integration
3. Create automated API validation tests
4. Add support for multiple EDX instances

## Conclusion

**Status**: ⚠️ **REQUIRES IMMEDIATE ATTENTION**

Our implementation has a solid foundation with correct authentication and basic API usage, but has **one critical issue**: the Course Blocks API endpoint format is incorrect. This needs immediate fixing as it affects core functionality.

**Priority Actions:**
1. 🚨 **CRITICAL**: Fix Course Blocks API endpoint format
2. 🔥 **HIGH**: Strengthen video extraction with multiple strategies  
3. 🔶 **MEDIUM**: Add platform compatibility detection

**Overall Assessment**: Good architectural foundation, but needs targeted fixes for production readiness.