from modeltranslation.translator import translator, TranslationOptions
from .models import Shnk, Qurilish_reglaament


class ShnkTranslationOptions(TranslationOptions):
    fields = ('name',)

translator.register(Shnk, ShnkTranslationOptions)


class Qurilish_reglaamentTranslationOptions(TranslationOptions):
    fields = ('group','name',)

translator.register(Qurilish_reglaament, Qurilish_reglaamentTranslationOptions)