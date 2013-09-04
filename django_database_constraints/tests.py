import os
import threading

from django.db import models, IntegrityError, OperationalError, connection, transaction
import django.forms
from django.test import TransactionTestCase
from django.test.client import RequestFactory
from django.views.generic import CreateView, UpdateView

from forms import TransactionalMixin
from views import CreateView as TransactionalCreateView, UpdateView as TransactionalUpdateView


class TestModel(models.Model):
    unique = models.IntegerField(unique=True)


class TestForm(django.forms.ModelForm):
    class Meta:
        model = TestModel


class TransactionalTestForm(TransactionalMixin, TestForm):
    pass


def get_acquiring_form(form_class, semaphore):
    class AcquiringForm(form_class):
        def save(self, *args, **kwargs):
            semaphore.acquire(True)
            return super(AcquiringForm, self).save(*args, **kwargs)
    return AcquiringForm


def get_releasing_form(form_class, semaphore):
    class ReleasingForm(form_class):
        def save(self, *args, **kwargs):
            ret = super(ReleasingForm, self).save(*args, **kwargs)
            semaphore.release()
            return ret
    return ReleasingForm


def get_acquiring_view(form_class, view_class, semaphore):
    AcquiringForm = get_acquiring_form(form_class, semaphore)
    fc = form_class
    class AcquiringView(view_class):
        model = fc._meta.model
        form_class = AcquiringForm
        success_url = '/'
    return AcquiringView

        
def get_releasing_view(form_class, view_class, semaphore):
    ReleasingForm = get_releasing_form(form_class, semaphore)
    fc = form_class
    class ReleasingView(view_class):
        model = fc._meta.model
        form_class = ReleasingForm
        success_url = '/'
    return ReleasingView


class TestConcurrencyBehaviour(TransactionTestCase):
    """
    What exactly happens when concurrent forms complete validation before trying to save?
    """

    def test_no_transactions(self):
        self.assertEqual(0, TestModel.objects.count())
        def first(semaphore):
            try:
                first.as_expected = None
                form = get_acquiring_form(TestForm, semaphore)({ 'unique': 1})
                form.is_valid()
                first.as_expected = False
                form.save()
            except IntegrityError:
                first.as_expected = True
            finally:
                connection.close()

        def second(semaphore):
            try:
                second.as_expected = False
                form = get_releasing_form(TestForm, semaphore)({ 'unique': 1})
                form.is_valid()
                form.save()
                second.as_expected = True
            finally:
                connection.close()

        semaphore = threading.Semaphore()
        semaphore.acquire()
        first_thread = threading.Thread(target=first, args=[semaphore])
        second_thread = threading.Thread(target=second, args=[semaphore])
        first_thread.daemon = True
        second_thread.daemon = True

        first_thread.start()
        second_thread.start()
        second_thread.join()
        first_thread.join()

        # okay, so the validation checks should both have passed
        # before either thread got to saving, so we should get the
        # releasing form (ie the second thread) having succeeded and
        # the first blowing up.
        self.assertEqual(True, first.as_expected)
        self.assertEqual(True, second.as_expected)
        self.assertEqual(1, TestModel.objects.count())

    def test_with_transactions(self):
        self.assertEqual(0, TestModel.objects.count())

        def first(semaphore):
            try:
                with transaction.atomic():
                    first.as_expected = None
                    form = get_acquiring_form(TestForm, semaphore)({ 'unique': 1})
                    form.is_valid()
                    first.as_expected = False
                    form.save()
            #except OperationalError:
            #    # sqlite can't cope with threads and transactions, really
            #    first.as_expected = True
            except IntegrityError:
                first.as_expected = True
            finally:
                connection.close()

        def second(semaphore):
            try:
                with transaction.atomic():
                    second.as_expected = False
                    form = get_releasing_form(TestForm, semaphore)({ 'unique': 1})
                    form.is_valid()
                    form.save()
                    second.as_expected = True
            finally:
                connection.close()

        semaphore = threading.Semaphore()
        semaphore.acquire()
        first_thread = threading.Thread(target=first, args=[semaphore])
        second_thread = threading.Thread(target=second, args=[semaphore])
        first_thread.daemon = True
        second_thread.daemon = True

        first_thread.start()
        second_thread.start()
        second_thread.join()
        first_thread.join()

        # okay, so the validation checks should both have passed
        # before either thread got to saving, so we should get the
        # releasing form (ie the second thread) having succeeded and
        # the first blowing up.
        self.assertEqual(True, first.as_expected)
        self.assertEqual(True, second.as_expected)
        self.assertEqual(1, TestModel.objects.count())


class TestTransactionalSave(TransactionTestCase):
    """Do our Form extensions work?"""
    # this is very similar to the concurrency tests above, but trying
    # to get better behaviour

    def test_form_raises_validationerror(self):
        class InnerTestForm(TransactionalTestForm):
            def save(self):
                raise django.forms.ValidationError("some message")

        form = InnerTestForm({ 'unique': 1})
        form.is_valid()
        try:
            form.tsave()
        except django.forms.ValidationError as e:
            pass
        self.assertEqual(1, len(form.non_field_errors()))
        self.assertEqual("some message", form.non_field_errors()[0])

    def test_form_raises_validationerror_list(self):
        class InnerTestForm(TransactionalTestForm):
            def save(self):
                raise django.forms.ValidationError(["some message", "some other message"])

        form = InnerTestForm({ 'unique': 1})
        form.is_valid()
        try:
            form.tsave()
        except django.forms.ValidationError as e:
            pass
        self.assertEqual(2, len(form.non_field_errors()))
        self.assertEqual({"some message", "some other message"}, set(form.non_field_errors()))

    def test_form_raises_validationerror_dict(self):
        class InnerTestForm(TransactionalTestForm):
            def save(self):
                raise django.forms.ValidationError(
                    {
                        "unique": ["some message", "some other message"]
                    }
                )

        form = InnerTestForm({ 'unique': 1})
        form.is_valid()
        try:
            form.tsave()
        except django.forms.ValidationError as e:
            pass
        field_errors = form.errors.get("unique")
        self.assertEqual(2, len(field_errors))
        self.assertEqual({"some message", "some other message"}, set(field_errors))

    def test_with_transactions(self):
        self.assertEqual(0, TestModel.objects.count())

        def first(semaphore):
            try:
                with transaction.atomic():
                    first.as_expected = None
                    form = get_acquiring_form(TransactionalTestForm, semaphore)({ 'unique': 1})
                    form.is_valid()
                    first.as_expected = False
                    form.tsave()
            except django.forms.ValidationError as e:
                first.as_expected = True
                first.exception = e
                first.form = form
            finally:
                connection.close()

        def second(semaphore):
            try:
                with transaction.atomic():
                    second.as_expected = False
                    form = get_releasing_form(TransactionalTestForm, semaphore)({ 'unique': 1})
                    form.is_valid()
                    form.tsave()
                    second.as_expected = True
            finally:
                connection.close()

        semaphore = threading.Semaphore()
        semaphore.acquire()
        first_thread = threading.Thread(target=first, args=[semaphore])
        second_thread = threading.Thread(target=second, args=[semaphore])
        first_thread.daemon = True
        second_thread.daemon = True

        first_thread.start()
        second_thread.start()
        second_thread.join()
        first_thread.join()

        # okay, so the validation checks should both have passed
        # before either thread got to saving, so we should get the
        # releasing form (ie the second thread) having succeeded and
        # the first blowing up with a ValidationError that is correctly
        # added as a non-field error.
        self.assertEqual(True, first.as_expected)
        self.assertEqual(True, second.as_expected)
        self.assertEqual(1, TestModel.objects.count())

        self.assertEqual(1, len(first.form._errors[django.forms.forms.NON_FIELD_ERRORS]))
        self.assertEqual(str(first.exception.messages[0]), first.form._errors[django.forms.forms.NON_FIELD_ERRORS][0])


class TestViews(TransactionTestCase):
    """Do our View extensions work?"""

    def setUp(self):
        self.factory = RequestFactory()

    def test_create(self):
        self._test_create(TransactionalTestForm)

    def test_create_default_tsave(self):
        self._test_create(TestForm)

    def test_create_override_conversion(self):
        class _CreateView(TransactionalCreateView):
            def validationerror_from_integrityerror(self, ierror):
                return django.forms.ValidationError("poop")
        first, second = self._test_create(TestForm, _CreateView)
        self.assertTrue("poop" in first.response.content)

    def _test_create(self, base_form, create_view=TransactionalCreateView):
        self.assertEqual(0, TestModel.objects.count())

        def first(semaphore):
            try:
                first.as_expected = False
                view = get_acquiring_view(base_form, create_view, semaphore).as_view()
                request = self.factory.post("/", { 'unique': '1' })
                first.response = view(request)
                first.response.render()
                first.as_expected = True
            finally:
                connection.close()

        def second(semaphore):
            try:
                second.as_expected = False
                view = get_releasing_view(base_form, create_view, semaphore).as_view()
                request = self.factory.post("/", { 'unique': '1' })
                second.response = view(request)
                second.as_expected = True
            finally:
                connection.close()

        semaphore = threading.Semaphore()
        semaphore.acquire()
        first_thread = threading.Thread(target=first, args=[semaphore])
        second_thread = threading.Thread(target=second, args=[semaphore])
        first_thread.daemon = True
        second_thread.daemon = True

        first_thread.start()
        second_thread.start()
        second_thread.join()
        first_thread.join()

        # okay, so the validation checks should both have passed
        # before either thread got to saving, so we should get the
        # releasing view (ie the second thread) having succeeded and
        # the first displaying a validation error on its form.
        self.assertEqual(True, first.as_expected)
        self.assertEqual(True, second.as_expected)
        self.assertEqual(1, TestModel.objects.count())

        self.assertEqual(200, first.response.status_code)
        self.assertTrue('errorlist' in first.response.content)
        self.assertTrue('errorlist' not in second.response.content)
        self.assertEqual(302, second.response.status_code)
        self.assertEqual('/', second.response['Location'])
        return first, second

    def test_update(self):
        self._test_update(TransactionalTestForm)

    def test_update_default_tsave(self):
        self._test_update(TestForm)

    def test_update_override_conversion(self):
        class _UpdateView(TransactionalUpdateView):
            def validationerror_from_integrityerror(self, ierror):
                return django.forms.ValidationError("poop")
        first, second = self._test_update(TestForm, _UpdateView)
        self.assertTrue("poop" in first.response.content)

    def _test_update(self, base_form, update_view=TransactionalUpdateView):
        self.assertEqual(0, TestModel.objects.count())
        tm1 = TestModel.objects.create(unique=1)
        tm2 = TestModel.objects.create(unique=2)

        def first(semaphore):
            try:
                first.as_expected = False
                view = get_acquiring_view(base_form, update_view, semaphore).as_view()
                request = self.factory.post("/", { 'id': tm1.pk, 'unique': '3' })
                first.response = view(request, pk=tm1.pk)
                first.response.render()
                first.as_expected = True
            finally:
                connection.close()

        def second(semaphore):
            try:
                second.as_expected = False
                view = get_releasing_view(base_form, update_view, semaphore).as_view()
                request = self.factory.post("/", { 'id': tm2.pk, 'unique': '3' })
                second.response = view(request, pk=tm2.pk)
                second.as_expected = True
            finally:
                connection.close()

        semaphore = threading.Semaphore()
        semaphore.acquire()
        first_thread = threading.Thread(target=first, args=[semaphore])
        second_thread = threading.Thread(target=second, args=[semaphore])
        first_thread.daemon = True
        second_thread.daemon = True

        first_thread.start()
        second_thread.start()
        second_thread.join()
        first_thread.join()

        # okay, so the validation checks should both have passed
        # before either thread got to saving, so we should get the
        # releasing view (ie the second thread) having succeeded and
        # the first displaying a validation error on its form.
        self.assertEqual(True, first.as_expected)
        self.assertEqual(True, second.as_expected)
        self.assertEqual(2, TestModel.objects.count())
        tm1 = TestModel.objects.get(pk=tm1.pk)
        self.assertEqual(1, tm1.unique)
        tm2 = TestModel.objects.get(pk=tm2.pk)
        self.assertEqual(3, tm2.unique)

        self.assertEqual(200, first.response.status_code)
        self.assertTrue('errorlist' in first.response.content)
        self.assertTrue('errorlist' not in second.response.content)
        self.assertEqual(302, second.response.status_code)
        self.assertEqual('/', second.response['Location'])
        return first, second
