import express, { Request } from 'express';

const app = express();
const port: number = parseInt(process.env.PORT ?? '3000');

app.use(express.json());

app.get<Request>('/', (req, res) => {
  console.log('Twitter OAuth');
});

app.listen(port, () => console.log(`Listening on port ${port}!`));
