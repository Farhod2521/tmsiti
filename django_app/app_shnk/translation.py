from modeltranslation.translator import translator, TranslationOptions
from .models import Shnk


class ShnkTranslationOptions(TranslationOptions):
    fields = ('name',)

translator.register(Shnk, ShnkTranslationOptions)