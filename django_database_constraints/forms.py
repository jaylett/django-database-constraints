from django import forms
from django.db import transaction, IntegrityError
from django.utils.encoding import force_text


def fallback_conversion(ierror):
    return forms.ValidationError([str(ierror)])


DEFAULT_CONVERTORS = [ fallback_conversion ]


def validationerror_from_integrityerror(ierror, convertors=None):
    if convertors is None:
        convertors = []
    convertors.extend(DEFAULT_CONVERTORS)
    for convertor in convertors:
        v = convertor(ierror)
        if v is not None:
            v.cause = ierror
            return v


def add_error_to_form(form, error, field=None):
    if field is None:
        field = forms.forms.NON_FIELD_ERRORS
    if field not in form._errors:
        form._errors[field] = form.error_class()
    form._errors[field].append(error)


def transactional_save(form, convertors=None):
    try:
        try:
            with transaction.atomic():
                # all "transactional" saves commit at once
                return form.save()
        except IntegrityError as e:
            raise validationerror_from_integrityerror(e, convertors)
    except forms.ValidationError as e:
        error_dict = e.update_error_dict({})
        for field, messages in error_dict.items():
            message_list = []
            for message in messages:
                if isinstance(message, forms.ValidationError):
                    message_list.extend(message.messages)
                else:
                    message_list.append(force_text(message))
            for m in message_list:
                add_error_to_form(form, m, field)
        raise


class TransactionalMixin(object):
    def tsave(self, convertors=None):
        # this allows you to override the behaviour, although since
        # it's pretty gnarly you may be better off not doing so
        return transactional_save(self, convertors)


class ModelForm(TransactionalMixin, forms.ModelForm):
    pass
