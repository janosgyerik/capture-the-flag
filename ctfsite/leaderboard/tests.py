import random
import string

from django.contrib.auth.models import User
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from .models import Team, TeamMember, Level, Submission, MAX_MEMBERS_PER_TEAM, encoded


def random_alphabetic(length=10):
    return ''.join(random.choices(string.ascii_lowercase, k=length))


def new_user(username=None):
    if username is None:
        username = random_alphabetic()
    user = User.objects.create(username=username)
    user.set_password(username)
    user.save()
    return user


def new_team():
    return Team.objects.create(name=random_alphabetic())


def new_level(answer=None):
    if answer is None:
        answer = random_alphabetic()
    return Level.objects.create(name=random_alphabetic(), answer=encoded(answer))


def count_teams():
    return Team.objects.count()


def count_team_members():
    return TeamMember.objects.count()


def count_submissions():
    return Submission.objects.count()


def login_redirect_url(url):
    return '/accounts/login/?next=' + url


class TeamModelTests(TestCase):
    def test_can_create_teams(self):
        for _ in range(3):
            team = new_team()
            for _ in range(MAX_MEMBERS_PER_TEAM):
                team.add_member(new_user())

        self.assertEqual(3, count_teams())
        self.assertEqual(3 * MAX_MEMBERS_PER_TEAM, count_team_members())

    def test_cannot_create_more_members_than_max(self):
        team = new_team()
        for _ in range(MAX_MEMBERS_PER_TEAM):
            team.add_member(new_user())

        self.assertRaisesMessage(ValueError, f"Team '{team.name}' is not accepting members", team.add_member, new_user())

    def test_cannot_add_same_member_twice(self):
        team = new_team()
        user = new_user()
        team.add_member(user)
        self.assertRaises(IntegrityError, team.add_member, user)

    def test_same_user_cannot_join_multiple_teams(self):
        user = new_user()
        team1 = new_team()
        team1.add_member(user)
        team2 = new_team()
        self.assertRaises(IntegrityError, team2.add_member, user)

    def test_remove_last_member_deletes_team(self):
        user = new_user()
        team = new_team()
        team.add_member(user)
        self.assertEqual(1, count_team_members())
        team.remove_member(user)
        self.assertEqual(0, count_team_members())

    def test_cannot_submit_when_team_is_empty(self):
        team = new_team()
        self.assertFalse(team.can_submit())

    def test_submit_fails_for_incorrect_answer(self):
        team = new_team()
        team.add_member(new_user())
        new_level()
        self.assertFalse(team.submit_attempt('incorrect'))

    def test_submit_accepts_correct_answer(self):
        answer = random_alphabetic()
        new_level(answer)

        user = new_user()
        team = new_team()
        team.add_member(user)
        self.assertEqual(0, team.next_level_index())
        self.assertTrue(team.can_submit())
        self.assertIsNotNone(team.next_level())

        self.assertTrue(team.submit_attempt(answer))
        self.assertEqual(1, team.next_level_index())
        self.assertFalse(team.can_submit())
        self.assertIsNone(team.next_level())

    def test_submit_accepts_correct_answer_sequence(self):
        answers = [random_alphabetic() for _ in range(6)]
        for answer in answers:
            new_level(answer)

        user = new_user()
        team = new_team()
        team.add_member(user)

        for i, answer in enumerate(answers):
            self.assertEqual(i, team.next_level_index())
            self.assertTrue(team.can_submit())
            self.assertIsNotNone(team.next_level())

            self.assertTrue(team.submit_attempt(answer))
            self.assertEqual(i + 1, team.next_level_index())

        self.assertFalse(team.can_submit())
        self.assertIsNone(team.next_level())


class LevelModelTests(TestCase):
    def new_level(self, name, answer):
        Level.objects.create(name=name, answer=encoded(answer))

    def test_cannot_create_level_with_same_name(self):
        self.new_level("foo", "bar")
        self.assertRaises(IntegrityError, self.new_level, "foo", "baz")

    def test_cannot_create_level_with_same_answer(self):
        self.new_level("foo", "bar")
        self.assertRaises(IntegrityError, self.new_level, "baz", "bar")


class TeamViewTests(TestCase):
    def test_anon_user_cannot_see_team_page(self):
        url = reverse('leaderboard:team')
        response = self.client.get(url)
        self.assertRedirects(response, login_redirect_url(url), status_code=302, fetch_redirect_response=False)

    def test_logged_in_user_sees_create_team_form_when_not_yet_member(self):
        user = new_user()
        self.client.login(username=user.username, password=user.username)
        response = self.client.get(reverse('leaderboard:team'))
        self.assertContains(response, "Team: None")
        self.assertContains(response, reverse('leaderboard:create-team'))


class CreateTeamViewTests(TestCase):
    def setUp(self):
        self.user = user = new_user()
        self.client.login(username=user.username, password=user.username)

    def test_logged_in_user_cannot_create_team_with_empty_name(self):
        response = self.client.post(reverse('leaderboard:create-team'), data={"team_name": ""})
        self.assertContains(response, "team_name: This field is required")

    def test_logged_in_user_can_create_team(self):
        response = self.client.post(reverse('leaderboard:create-team'), data={"team_name": "foo"})
        self.assertRedirects(response, reverse('leaderboard:team'), status_code=302, fetch_redirect_response=False)
        self.assertEqual('foo', Team.objects.first().name)

    def test_anon_user_cannot_create_team(self):
        self.client.logout()
        url = reverse('leaderboard:create-team')
        response = self.client.post(url, data={"team_name": "foo"})
        self.assertRedirects(response, login_redirect_url(url), status_code=302, fetch_redirect_response=False)
        self.assertEqual(0, count_teams())
        self.assertEqual(0, count_team_members())

    def test_logged_in_user_cannot_create_team_if_already_member_of_a_team(self):
        team = new_team()
        team.add_member(self.user)
        response = self.client.post(reverse('leaderboard:create-team'), data={"team_name": "foo"})
        self.assertContains(response, "UNIQUE constraint failed: leaderboard_teammember.user_id")


class SubmissionsViewTests(TestCase):
    def setUp(self):
        self.user = user = new_user()
        self.client.login(username=user.username, password=user.username)

    def test_anon_user_cannot_see_submissions_page(self):
        self.client.logout()
        url = reverse('leaderboard:submissions')
        response = self.client.get(url)
        self.assertRedirects(response, login_redirect_url(url), status_code=302, fetch_redirect_response=False)

    def test_logged_in_user_cannot_see_create_submission_form_when_not_yet_member(self):
        response = self.client.get(reverse('leaderboard:submissions'))
        expected_url = reverse('leaderboard:team')
        self.assertRedirects(response, expected_url, status_code=302, fetch_redirect_response=False)

    def test_logged_in_user_cannot_see_create_submission_form_when_no_more_levels(self):
        team = new_team()
        team.add_member(self.user)
        response = self.client.get(reverse('leaderboard:submissions'))
        self.assertContains(response, "Congratulations, you have captured the flag, well done!")
        self.assertNotContains(response, "Next level:")
        self.assertNotContains(response, reverse('leaderboard:create-submission'))

    def test_logged_in_user_sees_create_submission_form_when_there_are_more_levels(self):
        team = new_team()
        team.add_member(self.user)
        new_level()
        response = self.client.get(reverse('leaderboard:submissions'))
        self.assertNotContains(response, "Congratulations, you have captured the flag, well done!")
        self.assertContains(response, "Next level:")
        self.assertContains(response, reverse('leaderboard:create-submission'))


class CreateSubmissionViewTests(TestCase):
    def setUp(self):
        self.user = user = new_user()
        self.client.login(username=user.username, password=user.username)

        self.team = team = new_team()
        team.add_member(self.user)

        self.answer = answer = random_alphabetic()
        new_level(answer)

    def test_logged_in_user_cannot_create_submission_with_empty_answer(self):
        response = self.client.post(reverse('leaderboard:create-submission'), data={"answer_attempt": ""})
        self.assertContains(response, "answer_attempt: This field is required")
        self.assertEqual(0, self.team.next_level_index())
        self.assertEqual(0, count_submissions())

    def test_logged_in_user_cannot_create_submission_with_incorrect_answer(self):
        response = self.client.post(reverse('leaderboard:create-submission'), data={"answer_attempt": self.answer + "x"})
        self.assertContains(response, "Incorrect answer")
        self.assertEqual(0, self.team.next_level_index())
        self.assertEqual(0, count_submissions())

    def test_logged_in_user_cannot_create_submission_when_already_has_the_flag(self):
        self.client.post(reverse('leaderboard:create-submission'), data={"answer_attempt": self.answer})
        self.assertEqual(1, self.team.next_level_index())
        self.assertEqual(1, count_submissions())

        response = self.client.post(reverse('leaderboard:create-submission'), data={"answer_attempt": 'foo'})
        expected_url = reverse('leaderboard:submissions')
        self.assertRedirects(response, expected_url, status_code=302, fetch_redirect_response=False)

        self.assertEqual(1, self.team.next_level_index())
        self.assertEqual(1, count_submissions())

    def test_logged_in_user_can_create_submission_with_correct_answer(self):
        self.assertEqual(0, self.team.next_level_index())
        self.assertEqual(0, count_submissions())

        response = self.client.post(reverse('leaderboard:create-submission'), data={"answer_attempt": self.answer})
        expected_url = reverse('leaderboard:submissions') + '?passed=1'
        self.assertRedirects(response, expected_url, status_code=302, fetch_redirect_response=False)

        self.assertEqual(1, self.team.next_level_index())
        self.assertEqual(1, count_submissions())

    def test_anon_user_cannot_create_submission(self):
        self.client.logout()

        url = reverse('leaderboard:create-submission')
        response = self.client.post(url, data={"answer_attempt": self.answer})
        expected_url = login_redirect_url(url)
        self.assertRedirects(response, expected_url, status_code=302, fetch_redirect_response=False)

        self.assertEqual(0, self.team.next_level_index())
        self.assertEqual(0, count_submissions())
