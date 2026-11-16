-- parameters: city, day
delete from raw_user_observation
where city = %(city)s and date = %(day)s;
