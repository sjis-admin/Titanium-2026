from django.core.management.base import BaseCommand
from registration.models import Event, EventOption, Grade

class Command(BaseCommand):
    help = 'Creates the Valorant event'

    def handle(self, *args, **options):
        valorant_event, created = Event.objects.get_or_create(
            name='Valorant',
            defaults={
                'description': 'Valorant Tournament',
                'is_active': True,
            }
        )

        if created:
            self.stdout.write(self.style.SUCCESS('Successfully created Valorant event'))
        else:
            self.stdout.write(self.style.WARNING('Valorant event already exists'))

        # Add all grades to the event
        for grade in Grade.objects.all():
            valorant_event.target_grades.add(grade)

        EventOption.objects.get_or_create(
            event=valorant_event,
            name='Team',
            defaults={
                'event_type': 'TEAM',
                'fee': 500.00,
                'max_team_size': 5,
            }
        )

        self.stdout.write(self.style.SUCCESS('Successfully set up Valorant event options'))
