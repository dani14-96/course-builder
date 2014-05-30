# Copyright 2012 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS-IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Handlers that are not directly related to course content."""

__author__ = 'Saifu Angto (saifu@google.com)'

import gettext
import urlparse

import jinja2
import sites
import webapp2

from common import jinja_utils
from common import utils as common_utils
from common.crypto import XsrfTokenManager
from models import models
from models import transforms
from models.config import ConfigProperty
from models.courses import Course
from models.models import Student
from models.models import StudentProfileDAO
from models.models import TransientStudent
from models.roles import Roles

from google.appengine.api import users

# The name of the template dict key that stores a course's base location.
COURSE_BASE_KEY = 'gcb_course_base'

# The name of the template dict key that stores data from course.yaml.
COURSE_INFO_KEY = 'course_info'

TRANSIENT_STUDENT = TransientStudent()

# Whether to record page load/unload events in a database.
CAN_PERSIST_PAGE_EVENTS = ConfigProperty(
    'gcb_can_persist_page_events', bool, (
        'Whether or not to record student page interactions in a '
        'datastore. Without event recording, you cannot analyze student '
        'page interactions. On the other hand, no event recording reduces '
        'the number of datastore operations and minimizes the use of Google '
        'App Engine quota. Turn event recording on if you want to analyze '
        'this data.'),
    False)


# Whether to record tag events in a database.
CAN_PERSIST_TAG_EVENTS = ConfigProperty(
    'gcb_can_persist_tag_events', bool, (
        'Whether or not to record student tag interactions in a '
        'datastore. Without event recording, you cannot analyze student '
        'tag interactions. On the other hand, no event recording reduces '
        'the number of datastore operations and minimizes the use of Google '
        'App Engine quota. Turn event recording on if you want to analyze '
        'this data.'),
    False)


# Whether to record events in a database.
CAN_PERSIST_ACTIVITY_EVENTS = ConfigProperty(
    'gcb_can_persist_activity_events', bool, (
        'Whether or not to record student activity interactions in a '
        'datastore. Without event recording, you cannot analyze student '
        'activity interactions. On the other hand, no event recording reduces '
        'the number of datastore operations and minimizes the use of Google '
        'App Engine quota. Turn event recording on if you want to analyze '
        'this data.'),
    False)


# Date format string for displaying datetimes in UTC.
# Example: 2013-03-21 13:00 UTC
HUMAN_READABLE_DATETIME_FORMAT = '%Y-%m-%d, %H:%M UTC'

# Date format string for displaying dates. Example: 2013-03-21
HUMAN_READABLE_DATE_FORMAT = '%Y-%m-%d'

# Time format string for displaying times. Example: 01:16:40 UTC.
HUMAN_READABLE_TIME_FORMAT = '%H:%M:%S UTC'


class PageInitializer(object):
    """Abstract class that defines an interface to initialize page headers."""

    @classmethod
    def initialize(cls, template_value):
        raise NotImplementedError


class DefaultPageInitializer(PageInitializer):
    """Implements default page initializer."""

    @classmethod
    def initialize(cls, template_value):
        pass


class PageInitializerService(object):
    """Installs the appropriate PageInitializer."""
    _page_initializer = DefaultPageInitializer

    @classmethod
    def get(cls):
        return cls._page_initializer

    @classmethod
    def set(cls, page_initializer):
        cls._page_initializer = page_initializer


class ReflectiveRequestHandler(object):
    """Uses reflection to handle custom get() and post() requests.

    Use this class as a mix-in with any webapp2.RequestHandler to allow request
    dispatching to multiple get() and post() methods based on the 'action'
    parameter.

    Open your existing webapp2.RequestHandler, add this class as a mix-in.
    Define the following class variables:

        default_action = 'list'
        get_actions = ['default_action', 'edit']
        post_actions = ['save']

    Add instance methods named get_list(self), get_edit(self), post_save(self).
    These methods will now be called automatically based on the 'action'
    GET/POST parameter.
    """

    def create_xsrf_token(self, action):
        return XsrfTokenManager.create_xsrf_token(action)

    def get(self):
        """Handles GET."""
        action = self.request.get('action')
        if not action:
            action = self.default_action

        if action not in self.get_actions:
            self.error(404)
            return

        handler = getattr(self, 'get_%s' % action)
        if not handler:
            self.error(404)
            return

        return handler()

    def post(self):
        """Handles POST."""
        action = self.request.get('action')
        if not action or action not in self.post_actions:
            self.error(404)
            return

        handler = getattr(self, 'post_%s' % action)
        if not handler:
            self.error(404)
            return

        # Each POST request must have valid XSRF token.
        xsrf_token = self.request.get('xsrf_token')
        if not XsrfTokenManager.is_xsrf_token_valid(xsrf_token, action):
            self.error(403)
            return

        return handler()


def display_unit_title(unit):
    """Prepare an internationalized display for the unit title."""
    app_context = sites.get_course_for_current_request()
    if Course.get_environ(app_context)['course'].get(
            'display_unit_title_without_index'):
        return unit.title
    else:
        # I18N: Message displayed as title for unit
        return gettext.gettext('Unit %s - %s' % (unit.index, unit.title))


def display_short_unit_title(unit):
    """Prepare a short unit title."""
    app_context = sites.get_course_for_current_request()
    if Course.get_environ(app_context)['course'].get(
            'display_unit_title_without_index'):
        return unit.title
    if unit.type != 'U':
        return unit.title
    return '%s %s' % (gettext.gettext('Unit'), unit.index)


def display_lesson_title(unit, lesson):
    """Prepare an internationalized display for the unit title."""
    app_context = sites.get_course_for_current_request()
    if Course.get_environ(app_context)['course'].get(
            'display_unit_title_without_index'):
        return '%s %s' % (lesson.index, lesson.title)
    else:
        return '%s.%s %s' % (unit.index, lesson.index, lesson.title)


class ApplicationHandler(webapp2.RequestHandler):
    """A handler that is aware of the application context."""

    @classmethod
    def is_absolute(cls, url):
        return bool(urlparse.urlparse(url).scheme)

    @classmethod
    def get_base_href(cls, handler):
        """Computes current course <base> href."""
        base = handler.app_context.get_slug()
        if not base.endswith('/'):
            base = '%s/' % base

        # For IE to work with the <base> tag, its href must be an absolute URL.
        if not cls.is_absolute(base):
            parts = urlparse.urlparse(handler.request.url)
            base = urlparse.urlunparse(
                (parts.scheme, parts.netloc, base, None, None, None))
        return base

    def __init__(self, *args, **kwargs):
        super(ApplicationHandler, self).__init__(*args, **kwargs)
        self.template_value = {}

    def get_template(self, template_file, additional_dirs=None):
        """Computes location of template files for the current namespace."""
        self.template_value[COURSE_INFO_KEY] = self.app_context.get_environ()
        self.template_value['is_course_admin'] = Roles.is_course_admin(
            self.app_context)
        self.template_value[
            'is_read_write_course'] = self.app_context.fs.is_read_write()
        self.template_value['is_super_admin'] = Roles.is_super_admin()
        self.template_value[COURSE_BASE_KEY] = self.get_base_href(self)
        template_environ = self.app_context.get_template_environ(
            self.template_value[COURSE_INFO_KEY]['course']['locale'],
            additional_dirs
        )
        template_environ.filters[
            'gcb_tags'] = jinja_utils.get_gcb_tags_filter(self)
        template_environ.globals.update({
            'display_unit_title': display_unit_title,
            'display_short_unit_title': display_short_unit_title,
            'display_lesson_title': display_lesson_title})

        return template_environ.get_template(template_file)

    def render_template_to_html(self, template_values, template_file,
                                additional_dirs=None):
        template = self.get_template(template_file, additional_dirs)
        return jinja2.utils.Markup(
            template.render(template_values, autoescape=True))

    def canonicalize_url(self, location):
        """Adds the current namespace URL prefix to the relative 'location'."""
        is_relative = (
            not self.is_absolute(location) and
            not location.startswith(self.app_context.get_slug()))
        has_slug = (
            self.app_context.get_slug() and self.app_context.get_slug() != '/')
        if is_relative and has_slug:
            location = '%s%s' % (self.app_context.get_slug(), location)
        return location

    def redirect(self, location, normalize=True):
        if normalize:
            location = self.canonicalize_url(location)
        super(ApplicationHandler, self).redirect(location)


class BaseHandler(ApplicationHandler):
    """Base handler."""

    def __init__(self, *args, **kwargs):
        super(BaseHandler, self).__init__(*args, **kwargs)
        self.course = None

    def get_course(self):
        if not self.course:
            self.course = Course(self)
        return self.course

    def find_unit_by_id(self, unit_id):
        """Gets a unit with a specific id or fails with an exception."""
        return self.get_course().find_unit_by_id(unit_id)

    def get_units(self):
        """Gets all units in the course."""
        return self.get_course().get_units()

    def get_track_matching_student(self, student):
        """Gets units whose labels match those on the student."""
        return self.get_course().get_track_matching_student(student)

    def get_lessons(self, unit_id):
        """Gets all lessons (in order) in the specific course unit."""
        return self.get_course().get_lessons(unit_id)

    def get_progress_tracker(self):
        """Gets the progress tracker for the course."""
        return self.get_course().get_progress_tracker()

    def get_user(self):
        """Get the current user."""
        return users.get_current_user()

    def personalize_page_and_get_user(self):
        """If the user exists, add personalized fields to the navbar."""
        user = self.get_user()
        PageInitializerService.get().initialize(self.template_value)

        if hasattr(self, 'app_context'):
            self.template_value['can_register'] = self.app_context.get_environ(
                )['reg_form']['can_register']

        if user:
            self.template_value['email'] = user.email()
            self.template_value['logoutUrl'] = (
                users.create_logout_url(self.request.uri))
            self.template_value['transient_student'] = False

            # configure page events
            self.template_value['record_tag_events'] = (
                CAN_PERSIST_TAG_EVENTS.value)
            self.template_value['record_page_events'] = (
                CAN_PERSIST_PAGE_EVENTS.value)
            self.template_value['record_events'] = (
                CAN_PERSIST_ACTIVITY_EVENTS.value)
            self.template_value['event_xsrf_token'] = (
                XsrfTokenManager.create_xsrf_token('event-post'))
        else:
            self.template_value['loginUrl'] = users.create_login_url(
                self.request.uri)
            self.template_value['transient_student'] = True
            return None

        return user

    def personalize_page_and_get_enrolled(
        self, supports_transient_student=False):
        """If the user is enrolled, add personalized fields to the navbar."""
        user = self.personalize_page_and_get_user()
        if user is None:
            student = TRANSIENT_STUDENT
        else:
            student = Student.get_enrolled_student_by_email(user.email())
            if not student:
                self.template_value['transient_student'] = True
                student = TRANSIENT_STUDENT

        if student.is_transient:
            if supports_transient_student and (
                    self.app_context.get_environ()['course']['browsable']):
                return TRANSIENT_STUDENT
            elif user is None:
                self.redirect(
                    users.create_login_url(self.request.uri), normalize=False
                )
                return None
            else:
                self.redirect('/preview')
                return None

        # Patch Student models which (for legacy reasons) do not have a user_id
        # attribute set.
        if not student.user_id:
            student.user_id = user.user_id()
            student.put()

        return student

    def assert_xsrf_token_or_fail(self, request, action):
        """Asserts the current request has proper XSRF token or fails."""
        token = request.get('xsrf_token')
        if not token or not XsrfTokenManager.is_xsrf_token_valid(token, action):
            self.error(403)
            return False
        return True

    def render(self, template_file):
        """Renders a template."""
        template = self.get_template(template_file)
        self.response.out.write(template.render(self.template_value))


class BaseRESTHandler(BaseHandler):
    """Base REST handler."""

    def assert_xsrf_token_or_fail(self, token_dict, action, args_dict):
        """Asserts that current request has proper XSRF token or fails."""
        token = token_dict.get('xsrf_token')
        if not token or not XsrfTokenManager.is_xsrf_token_valid(token, action):
            transforms.send_json_response(
                self, 403,
                'Bad XSRF token. Please reload the page and try again',
                args_dict)
            return False
        return True

    def validation_error(self, message, key=None):
        """Deliver a validation message."""
        if key:
            transforms.send_json_response(
                self, 412, message, payload_dict={'key': key})
        else:
            transforms.send_json_response(self, 412, message)


class PreviewHandler(BaseHandler):
    """Handler for viewing course preview."""

    def get(self):
        """Handles GET requests."""
        user = self.personalize_page_and_get_user()
        if user is None:
            student = TRANSIENT_STUDENT
        else:
            student = Student.get_enrolled_student_by_email(user.email())
            if not student:
                student = TRANSIENT_STUDENT

        # If the course is browsable, or the student is logged in and
        # registered, redirect to the main course page.
        if ((student and not student.is_transient) or
            self.app_context.get_environ()['course']['browsable']):
            self.redirect('/course')
            return

        self.template_value['transient_student'] = True
        self.template_value['can_register'] = self.app_context.get_environ(
            )['reg_form']['can_register']
        self.template_value['navbar'] = {'course': True}
        self.template_value['units'] = self.get_units()
        self.template_value['show_registration_page'] = True

        course = self.app_context.get_environ()['course']
        self.template_value['video_exists'] = bool(
            'main_video' in course and
            'url' in course['main_video'] and
            course['main_video']['url'])
        self.template_value['image_exists'] = bool(
            'main_image' in course and
            'url' in course['main_image'] and
            course['main_image']['url'])

        if user:
            profile = StudentProfileDAO.get_profile_by_user_id(user.user_id())
            additional_registration_fields = self.app_context.get_environ(
                )['reg_form']['additional_registration_fields']
            if profile is not None and not additional_registration_fields:
                self.template_value['show_registration_page'] = False
                self.template_value['register_xsrf_token'] = (
                    XsrfTokenManager.create_xsrf_token('register-post'))
        self.render('preview.html')


class RegisterHandler(BaseHandler):
    """Handler for course registration."""

    def get(self):
        """Handles GET request."""
        user = self.personalize_page_and_get_user()
        if not user:
            self.redirect(
                users.create_login_url(self.request.uri), normalize=False)
            return

        student = Student.get_enrolled_student_by_email(user.email())
        if student:
            self.redirect('/course')
            return

        can_register = self.app_context.get_environ(
            )['reg_form']['can_register']
        if not can_register:
            self.redirect('/course#registration_closed')
            return

        # pre-fill nick name from the profile if available
        self.template_value['current_name'] = ''
        profile = StudentProfileDAO.get_profile_by_user_id(user.user_id())
        if profile and profile.nick_name:
            self.template_value['current_name'] = profile.nick_name

        self.template_value['navbar'] = {}
        self.template_value['transient_student'] = True
        self.template_value['register_xsrf_token'] = (
            XsrfTokenManager.create_xsrf_token('register-post'))

        self.render('register.html')

    def post(self):
        """Handles POST requests."""
        user = self.personalize_page_and_get_user()
        if not user:
            self.redirect(
                users.create_login_url(self.request.uri), normalize=False)
            return

        if not self.assert_xsrf_token_or_fail(self.request, 'register-post'):
            return

        can_register = self.app_context.get_environ(
            )['reg_form']['can_register']
        if not can_register:
            self.redirect('/course#registration_closed')
            return

        if 'name_from_profile' in self.request.POST.keys():
            profile = StudentProfileDAO.get_profile_by_user_id(user.user_id())
            name = profile.nick_name
        else:
            name = self.request.get('form01')

        Student.add_new_student_for_current_user(
            name, transforms.dumps(self.request.POST.items()))
        # Render registration confirmation page
        self.redirect('/course#registration_confirmation')


class ForumHandler(BaseHandler):
    """Handler for forum page."""

    def get(self):
        """Handles GET requests."""
        student = self.personalize_page_and_get_enrolled(
            supports_transient_student=True)
        if not student:
            return

        self.template_value['navbar'] = {'forum': True}
        self.render('forum.html')


class StudentProfileHandler(BaseHandler):
    """Handles the click to 'Progress' link in the nav bar."""

    EXTRA_STUDENT_DATA_PROVIDERS = []

    def get(self):
        """Handles GET requests."""
        student = self.personalize_page_and_get_enrolled()
        if not student:
            return

        track_labels = models.LabelDAO.get_all_of_type(
            models.LabelDTO.LABEL_TYPE_COURSE_TRACK)
        track_label_ids = set([label.id for label in track_labels])

        course = self.get_course()
        units = []
        for unit in course.get_units():
            # Don't show assessments that are part of units.
            if course.get_parent_unit(unit.unit_id):
                continue

            unit_dict = {
                'unit_id': unit.unit_id,
                'title': unit.title,
                }
            if hasattr(unit, 'labels'):
                unit_dict['labels'] = [
                    int(x)
                    for x in common_utils.text_to_list(unit.labels)
                    if int(x) in track_label_ids]
            else:
                unit_dict['labels'] = []
            units.append(unit_dict)

        name = student.name
        profile = student.profile
        if profile:
            name = profile.nick_name
        student_labels = [
            int(x) for x in common_utils.text_to_list(student.labels)
            if int(x) in track_label_ids]

        self.template_value['navbar'] = {'progress': True}
        self.template_value['student'] = student
        self.template_value['student_name'] = name
        self.template_value['date_enrolled'] = student.enrolled_on.strftime(
            HUMAN_READABLE_DATE_FORMAT)
        self.template_value['score_list'] = course.get_all_scores(student)
        self.template_value['overall_score'] = course.get_overall_score(student)
        self.template_value['student_edit_xsrf_token'] = (
            XsrfTokenManager.create_xsrf_token('student-edit'))
        self.template_value['can_edit_name'] = (
            not models.CAN_SHARE_STUDENT_PROFILE.value)
        self.template_value['track_labels'] = track_labels
        self.template_value['student_labels'] = student_labels
        self.template_value['units'] = units

        # Append any extra data which is provided by modules
        extra_student_data = {}
        for data_provider in self.EXTRA_STUDENT_DATA_PROVIDERS:
            extra_student_data.update(data_provider(student, course))
        self.template_value['extra_student_data'] = extra_student_data

        self.render('student_profile.html')


class StudentEditStudentHandler(BaseHandler):
    """Handles edits to student records by students."""

    def post(self):
        """Handles POST requests."""
        student = self.personalize_page_and_get_enrolled()
        if not student:
            return

        if not self.assert_xsrf_token_or_fail(self.request, 'student-edit'):
            return

        Student.rename_current(self.request.get('name'))

        self.redirect('/student/home')


class StudentSetTracksHandler(BaseHandler):
    """Handles submission of student tracks selections."""

    def post(self):
        student = self.personalize_page_and_get_enrolled()
        if not student:
            return
        if not self.assert_xsrf_token_or_fail(self.request, 'student-edit'):
            return

        all_track_labels = set(
            [label.id
             for label in models.LabelDAO.get_all_of_type(
                 models.LabelDTO.LABEL_TYPE_COURSE_TRACK)])
        new_track_labels = set(
            [int(label_id)
             for label_id in self.request.get_all('labels')
             if label_id and int(label_id) in all_track_labels])
        student_labels = set(
            [int(label_id)
             for label_id in common_utils.text_to_list(student.labels)
             if label_id])

        # Remove all existing track (and only track) labels from student,
        # then merge in selected set from form.
        student_labels = student_labels.difference(all_track_labels)
        student_labels = student_labels.union(new_track_labels)
        models.Student.set_labels_for_current(
            common_utils.list_to_text(list(student_labels)))

        self.redirect('/student/home')


class StudentUnenrollHandler(BaseHandler):
    """Handler for students to unenroll themselves."""

    def get(self):
        """Handles GET requests."""
        student = self.personalize_page_and_get_enrolled()
        if not student:
            return

        self.template_value['student'] = student
        self.template_value['navbar'] = {}
        self.template_value['student_unenroll_xsrf_token'] = (
            XsrfTokenManager.create_xsrf_token('student-unenroll'))
        self.render('unenroll_confirmation_check.html')

    def post(self):
        """Handles POST requests."""
        student = self.personalize_page_and_get_enrolled()
        if not student:
            return

        if not self.assert_xsrf_token_or_fail(self.request, 'student-unenroll'):
            return

        Student.set_enrollment_status_for_current(False)

        self.template_value['navbar'] = {}
        self.template_value['transient_student'] = True
        self.render('unenroll_confirmation.html')
