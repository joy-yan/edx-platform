# -*- coding: utf-8 -*-
"""
Tests for credit course models.
"""

import ddt
from django.test import TestCase
from nose.plugins.attrib import attr
from opaque_keys.edx.keys import CourseKey

from openedx.core.djangoapps.credit.models import CreditCourse, CreditRequirement, CreditRequirementStatus
from student.models import get_retired_username_by_username
from student.tests.factories import UserFactory

from ..models import CreditRequest, CreditProvider, CreditCourse


def add_credit_course(course_key):
    """ Add the course as a credit

    Returns:
        CreditCourse object
    """
    credit_course = CreditCourse(course_key=course_key, enabled=True)
    credit_course.save()
    return credit_course


@attr(shard=2)
@ddt.ddt
class CreditEligibilityModelTests(TestCase):
    """
    Tests for credit models used to track credit eligibility.
    """

    def setUp(self):
        super(CreditEligibilityModelTests, self).setUp()
        self.course_key = CourseKey.from_string("edX/DemoX/Demo_Course")

    @ddt.data(False, True)
    def test_is_credit_course(self, is_credit):
        CreditCourse(course_key=self.course_key, enabled=is_credit).save()
        if is_credit:
            self.assertTrue(CreditCourse.is_credit_course(self.course_key))
        else:
            self.assertFalse(CreditCourse.is_credit_course(self.course_key))

    def test_get_course_requirements(self):
        credit_course = add_credit_course(self.course_key)
        requirement = {
            "namespace": "grade",
            "name": "grade",
            "display_name": "Grade",
            "criteria": {
                "min_grade": 0.8
            },
        }
        credit_req, created = CreditRequirement.add_or_update_course_requirement(credit_course, requirement, 0)
        self.assertEqual(credit_course, credit_req.course)
        self.assertEqual(created, True)
        requirements = CreditRequirement.get_course_requirements(self.course_key)
        self.assertEqual(len(requirements), 1)

    def test_add_course_requirement_namespace(self):
        credit_course = add_credit_course(self.course_key)
        requirement = {
            "namespace": "grade",
            "name": "grade",
            "display_name": "Grade",
            "criteria": {
                "min_grade": 0.8
            },
        }
        credit_req, created = CreditRequirement.add_or_update_course_requirement(credit_course, requirement, 0)
        self.assertEqual(credit_course, credit_req.course)
        self.assertEqual(created, True)

        requirement = {
            "namespace": "new_grade",
            "name": "new_grade",
            "display_name": "New Grade",
            "criteria": {},
        }
        credit_req, created = CreditRequirement.add_or_update_course_requirement(credit_course, requirement, 1)
        self.assertEqual(credit_course, credit_req.course)
        self.assertEqual(created, True)

        requirements = CreditRequirement.get_course_requirements(self.course_key)
        self.assertEqual(len(requirements), 2)

        requirements = CreditRequirement.get_course_requirements(self.course_key, namespace="grade")
        self.assertEqual(len(requirements), 1)


class CreditRequirementStatusTests(TestCase):
    """
    Tests for credit requirement status models.
    """

    def setUp(self):
        super(CreditRequirementStatusTests, self).setUp()
        self.course_key = CourseKey.from_string("edX/DemoX/Demo_Course")
        self.old_username = "username"
        self.retired_username = get_retired_username_by_username(self.old_username)
        self.credit_course = add_credit_course(self.course_key)

    def add_course_requirements(self):
        """
        Add requirements to course.
        """
        requirements = (
            {
                "namespace": "grade",
                "name": "grade",
                "display_name": "Grade",
                "criteria": {
                    "min_grade": 0.8
                }
            },
            {
                "namespace": "new_grade",
                "name": "new_grade",
                "display_name": "new_grade",
                "criteria": {
                    "min_grade": 0.8
                },
            }
        )

        for i, requirement in enumerate(requirements):
            credit_requirement, _ = CreditRequirement.add_or_update_course_requirement(
                self.credit_course,
                requirement,
                i
            )
            CreditRequirementStatus.add_or_update_requirement_status(
                self.old_username,
                credit_requirement,
                "satisfied",
                {
                    "final_grade": 0.95
                }
            )

    def test_retire_user(self):
        self.add_course_requirements()

        retirement_succeeded = CreditRequirementStatus.retire_user(self.old_username)
        self.assertTrue(retirement_succeeded)

        old_username_records_exist = CreditRequirementStatus.objects.filter(
            username=self.old_username
        ).exists()
        self.assertFalse(old_username_records_exist)

        new_username_records_exist = CreditRequirementStatus.objects.filter(username=self.retired_username).exists()
        self.assertTrue(new_username_records_exist)

    def test_retire_user_with_data(self):
        retirement_succeeded = CreditRequirementStatus.retire_user(self.retired_username)
        self.assertFalse(retirement_succeeded)


class CreditRequestTest(TestCase):
    """
    The CreditRequest model's test suite.
    """

    def setUp(self):
        super(CreditRequestTest, self).setUp()
        self.user = UserFactory.create()
        self.credit_course = CreditCourse.objects.create()
        self.provider = CreditProvider.objects.create()

    def test_can_retire_user_from_credit_request(self):
        test_parameters = {'hi': 'there'}
        CreditRequest.objects.create(
            username=self.user.username,
            course=self.credit_course,
            provider=self.provider,
            parameters=test_parameters,
        )

        credit_request_before_retire = CreditRequest.objects.filter(
            username=self.user.username
        )[0]

        self.assertEqual(credit_request_before_retire.parameters, test_parameters)

        user_was_retired = CreditRequest.retire_user(
            original_username=self.user.username,
            retired_username=get_retired_username_by_username(self.user.username)
        )
        credit_request_before_retire.refresh_from_db()
        credit_requests_after_retire = CreditRequest.objects.filter(
            username=self.user.username
        )

        self.assertTrue(user_was_retired)
        self.assertEqual(credit_request_before_retire.parameters, {})
        self.assertFalse(credit_requests_after_retire.exists())

    def test_cannot_retire_nonexistent_user(self):
        test_parameters = {'hi': 'there'}
        CreditRequest.objects.create(
            username=self.user.username,
            course=self.credit_course,
            provider=self.provider,
            parameters=test_parameters,
        )
        another_user = UserFactory.create()

        credit_request_before_retire = CreditRequest.objects.filter(
            username=self.user.username
        )[0]

        was_retired = CreditRequest.retire_user(
            original_username=another_user.username,
            retired_username=get_retired_username_by_username(another_user.username)
        )
        credit_request_before_retire.refresh_from_db()

        self.assertFalse(was_retired)
        self.assertEqual(credit_request_before_retire.parameters, test_parameters)
